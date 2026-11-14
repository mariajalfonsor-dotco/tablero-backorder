"""Lógica del Tablero Backorder Yokomotor 173.

Base de datos SQLite (datos/backorder.db), comparación con el Excel de fábrica,
lectura de la lista de empaque (PDF), reportes en PDF y Excel.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "datos" / "backorder.db"
OPEN = {"Pendiente", "Parcial"}
ESTADOS = ["Pendiente", "Parcial", "Llegó", "Cancelado"]
CANALES_BASE = ["Colisión", "Mecanica", "Mostrador", "Boutique", "Stock"]
CAMPOS = ["pedido", "fecha", "ref", "desc", "cant", "cantFab", "envio", "eta", "canal",
          "cliente", "resp", "llegada", "estado", "nota"]
_lock = threading.Lock()


# ---------------------------------------------------------------- utilidades
def hoy() -> str:
    return dt.date.today().isoformat()


def fmt_d(s) -> str:
    if not s:
        return ""
    try:
        y, m, d = str(s)[:10].split("-")
        return f"{d}/{m}/{y}"
    except ValueError:
        return str(s)


def fold(s) -> str:
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def norm_ref(v) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def norm_ped(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return re.sub(r"\D", "", str(v or "")).lstrip("0")


def clave(pedido, ref) -> str:
    return norm_ped(pedido) + "|" + norm_ref(ref)


def to_iso(v):
    """Convierte fechas de Excel/texto a 'AAAA-MM-DD'. Devuelve None si no es fecha."""
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date().isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    try:  # pandas Timestamp
        import pandas as pd
        if isinstance(v, pd.Timestamp):
            return None if pd.isna(v) else v.date().isoformat()
    except Exception:
        pass
    if isinstance(v, (int, float)) and 20000 < v < 80000:
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}"
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$", s)
    if m:
        y = m[3] if len(m[3]) == 4 else "20" + m[3]
        return f"{y}-{int(m[2]):02d}-{int(m[1]):02d}"
    return None


def to_num(v):
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace(",", "."))
    except ValueError:
        return None
    if n != n:  # NaN
        return None
    return int(n) if n.is_integer() else n


def map_estado(v):
    s = fold(v)
    if not s:
        return None
    if "cancel" in s or "anulad" in s:
        return "Cancelado"
    if "parcial" in s:
        return "Parcial"
    if "lleg" in s or "entregad" in s or "recibid" in s:
        return "Llegó"
    if "pend" in s or "backorder" in s or s == "bo" or "b/o" in s:
        return "Pendiente"
    return None


def eta_calculada(r: dict):
    """ETA calculada = fecha de pedido + días del tipo de envío (28 aéreo, 66 marítimo). None si falta alguno."""
    try:
        dias = int(r.get("envio") or 0)
    except (TypeError, ValueError):
        return None
    if not dias or not r.get("fecha"):
        return None
    return sumar_dias(str(r["fecha"])[:10], dias)


def eta_mostrada(r: dict):
    """(fecha, es_calculada): la ETA de Toyota si existe; si no, la calculada por tipo de envío."""
    if r.get("eta"):
        return r["eta"], False
    c = eta_calculada(r)
    return (c, True) if c else (None, False)


def lead_time(a, b):
    """Días hábiles (lunes a viernes) entre fecha de pedido y llegada, incluyendo ambos."""
    if not a or not b:
        return None
    d1, d2 = dt.date.fromisoformat(a[:10]), dt.date.fromisoformat(b[:10])
    sign = 1
    if d2 < d1:
        d1, d2, sign = d2, d1, -1
    n = 0
    d = d1
    while d <= d2:
        if d.weekday() < 5:
            n += 1
        d += dt.timedelta(days=1)
    return n * sign


def sumar_dias(fecha: str | None, dias: int) -> str:
    base = dt.date.fromisoformat(fecha) if fecha else dt.date.today()
    return (base + dt.timedelta(days=dias)).isoformat()


# ------------------------------------------------------------- base de datos
# Si existe DATABASE_URL (variable de entorno o secreto de Streamlit) se usa Postgres
# (Supabase). Si no, se usa el archivo SQLite datos/backorder.db.
_pool = None


def _db_url():
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


def usa_postgres() -> bool:
    return bool(_db_url())


class _Cx:
    """Conexión mínima común para SQLite y Postgres (usa ? como marcador en ambos)."""

    def __init__(self, raw, pg):
        self.raw, self.pg = raw, pg

    def _q(self, sql):
        return sql.replace("?", "%s") if self.pg else sql

    def execute(self, sql, params=()):
        return self.raw.execute(self._q(sql), params)

    def executemany(self, sql, seq):
        seq = list(seq)
        if not seq:
            return
        if self.pg:
            with self.raw.cursor() as cur:
                cur.executemany(self._q(sql), seq)
        else:
            self.raw.executemany(sql, seq)


@contextmanager
def conectar():
    if usa_postgres():
        global _pool
        if _pool is None:
            from psycopg_pool import ConnectionPool
            _pool = ConnectionPool(_db_url(), min_size=1, max_size=4, open=True, timeout=30,
                                   kwargs={"prepare_threshold": None})
        with _pool.connection() as c:  # confirma al salir, deshace si hay error
            yield _Cx(c, True)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.execute("pragma journal_mode=wal")
        try:
            yield _Cx(c, False)
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()


def iniciar_db():
    with conectar() as c:
        for sql in ("create table if not exists repuestos(id text primary key, data text not null)",
                    "create table if not exists cargas(id text primary key, ts text, data text not null)",
                    "create table if not exists empaques(id text primary key, ts text, data text not null)",
                    "create table if not exists config(key text primary key, value text)"):
            c.execute(sql)
    if not usa_postgres():
        respaldo_diario()


def respaldo_diario(guardar: int = 30):
    """Copia el archivo SQLite una vez al día en datos/respaldos (solo en modo local)."""
    carpeta = DB_PATH.parent / "respaldos"
    destino = carpeta / f"backorder_{hoy()}.db"
    if destino.exists() or not DB_PATH.exists():
        return
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as src, sqlite3.connect(destino) as dst:
            src.backup(dst)
        for viejo in sorted(carpeta.glob("backorder_*.db"))[:-guardar]:
            viejo.unlink()
    except Exception:
        pass


def cargar_repuestos() -> dict[str, dict]:
    with conectar() as c:
        return {i: json.loads(d) for i, d in c.execute("select id, data from repuestos").fetchall()}


def contar_repuestos() -> int:
    with conectar() as c:
        return c.execute("select count(*) from repuestos").fetchone()[0]


def guardar_cambios(patch: dict[str, dict]):
    """Mezcla campos en repuestos existentes. Un valor None borra el campo."""
    if not patch:
        return
    ids = list(patch)
    with _lock, conectar() as c:
        actuales = {}
        for i in range(0, len(ids), 400):
            parte = ids[i:i + 400]
            q = "select id, data from repuestos where id in (" + ",".join("?" * len(parte)) + ")"
            actuales.update({rid: json.loads(d) for rid, d in c.execute(q, parte).fetchall()})
        filas = []
        for rid, campos in patch.items():
            r = actuales.get(rid)
            if r is None:
                continue
            for k, v in campos.items():
                if v is None:
                    r.pop(k, None)
                else:
                    r[k] = v
            filas.append((json.dumps(r, ensure_ascii=False), rid))
        c.executemany("update repuestos set data=? where id=?", filas)


def agregar_repuestos(lista: list[dict]) -> list[str]:
    ids, filas = [], []
    with _lock, conectar() as c:
        n = 0
        for (d,) in c.execute("select data from repuestos").fetchall():
            try:
                n = max(n, int(json.loads(d).get("n") or 0))
            except (TypeError, ValueError):
                pass
        for r in lista:
            n += 1
            r = dict(r, n=n)
            rid = "r" + secrets.token_hex(6)
            filas.append((rid, json.dumps(r, ensure_ascii=False)))
            ids.append(rid)
        c.executemany("insert into repuestos values(?,?)", filas)
    return ids


def borrar_repuesto(rid: str):
    with _lock, conectar() as c:
        c.execute("delete from repuestos where id=?", (rid,))


def config() -> dict:
    with conectar() as c:
        return dict(c.execute("select key, value from config").fetchall())


def set_config(**kw):
    with conectar() as c:
        c.executemany("insert into config values(?,?) on conflict(key) do update set value=excluded.value",
                      list(kw.items()))


def _lista(tabla):
    with conectar() as c:
        return [dict(json.loads(d), id=i) for i, d in
                c.execute(f"select id, data from {tabla} order by ts desc limit 100").fetchall()]


def cargas() -> list[dict]:
    return _lista("cargas")


def empaques() -> list[dict]:
    return _lista("empaques")


def _guardar(tabla, rid, doc):
    with conectar() as c:
        c.execute(f"insert into {tabla} values(?,?,?) on conflict(id) do update set ts=excluded.ts, data=excluded.data",
                  (rid, doc.get("ts"), json.dumps(doc, ensure_ascii=False)))


def exportar_respaldo() -> bytes:
    """Respaldo completo (repuestos, cargas, listas de empaque y configuración) en JSON."""
    with conectar() as c:
        doc = {"formato": "tablero-backorder", "version": 1, "generado": dt.datetime.now().isoformat(timespec="seconds"),
               "repuestos": {i: json.loads(d) for i, d in c.execute("select id, data from repuestos").fetchall()},
               "cargas": [[i, ts, json.loads(d)] for i, ts, d in c.execute("select id, ts, data from cargas").fetchall()],
               "empaques": [[i, ts, json.loads(d)] for i, ts, d in c.execute("select id, ts, data from empaques").fetchall()],
               "config": dict(c.execute("select key, value from config").fetchall())}
    return json.dumps(doc, ensure_ascii=False).encode("utf-8")


def importar_respaldo(data: bytes) -> int:
    """Carga un respaldo JSON (de exportar_respaldo) en una base vacía. Devuelve cuántos repuestos cargó."""
    doc = json.loads(data.decode("utf-8-sig"))
    if doc.get("formato") != "tablero-backorder":
        raise ValueError("El archivo no es un respaldo del Tablero Backorder.")
    with _lock, conectar() as c:
        if c.execute("select count(*) from repuestos").fetchone()[0]:
            raise ValueError("El tablero ya tiene datos; el respaldo solo se carga en un tablero vacío.")
        c.executemany("insert into repuestos values(?,?)",
                      [(i, json.dumps(r, ensure_ascii=False)) for i, r in doc["repuestos"].items()])
        for tabla in ("cargas", "empaques"):
            c.executemany(f"insert into {tabla} values(?,?,?) on conflict(id) do nothing",
                          [(i, ts, json.dumps(d, ensure_ascii=False)) for i, ts, d in doc.get(tabla, [])])
        c.executemany("insert into config values(?,?) on conflict(key) do update set value=excluded.value",
                      list(doc.get("config", {}).items()))
    return len(doc["repuestos"])


# ------------------------------------------------------ estados y categorías
def cat(r: dict, hoy_iso: str | None = None) -> str:
    hoy_iso = hoy_iso or hoy()
    if r.get("estado") == "Llegó":
        return "llego"
    if r.get("estado") not in OPEN:
        return "otro"
    if r.get("revisar"):
        return "revisar"
    if r.get("sinEtd") or not r.get("eta"):
        return "sinetd"
    return "vencida" if r["eta"] < hoy_iso else "aldia"


def estado_mostrado(r: dict, hoy_iso: str | None = None) -> str:
    c = cat(r, hoy_iso)
    if c == "vencida":
        return "Alerta"
    if c == "revisar":
        return "Revisar"
    if c == "sinetd":
        return "Sin ETD"
    e = r.get("estado") or ""
    if e == "Parcial" and r.get("recibido") is not None:
        return f"Parcial {r['recibido']}/{r.get('cant') if r.get('cant') is not None else '?'}"
    return e


def es_nuevo(r: dict, cfg: dict) -> bool:
    return bool(r.get("agregado") and cfg.get("actualizado") and r["agregado"] == cfg["actualizado"])


def campos_actualizados(r: dict, cfg: dict) -> list[str]:
    cm = r.get("cambio") or {}
    if es_nuevo(r, cfg) or not cfg.get("actualizado") or cm.get("fecha") != cfg.get("actualizado"):
        return []
    return list(cm.get("campos") or [])


def canal_key(c) -> str:
    k = re.sub(r"[^a-z]", "", fold(c))
    if k.startswith("stock") or "almacen" in k:
        return "stock"
    return k if k in ("mostrador", "mecanica", "colision", "boutique") else "otro"


# ------------------------------------------------------ Excel de fábrica
FIELDS = [
    ("ref", "Referencia (obligatoria)", [r"^material$", r"^refer", r"n.?mero de parte|part ?n|p/n", r"^c[oó]digo"]),
    ("pedido", "Pedido", [r"doc\.?\s*ventas", r"^pedido$", r"^(n.?mero de )?pedido|^orden|^order|^po$|^oc$"]),
    ("eta", "ETA (ETA_DEALER)", [r"eta_?dealer", r"^eta", r"eta|estimad|promes|fecha.*(entrega|lleg)"]),
    ("cant", "Cantidad pendiente", [r"ctd\.?\s*pend", r"cant.*pend|pendiente", r"^cant|qty|quant"]),
    ("estado", "Estado", [r"^estado|^status|situaci"]),
    ("desc", "Descripción", [r"n.?mero de material", r"desc|texto"]),
    ("fecha", "Fecha pedido", [r"fecha.*pedido", r"^fecha$"]),
]


def leer_excel(archivo) -> dict[str, list[list]]:
    """Devuelve {hoja: filas} con los valores crudos de cada hoja."""
    import pandas as pd
    nombre = getattr(archivo, "name", "").lower()
    if nombre.endswith(".csv"):
        df = pd.read_csv(archivo, header=None, dtype=object, sep=None, engine="python")
        hojas = {"CSV": df}
    else:
        hojas = pd.read_excel(archivo, sheet_name=None, header=None, dtype=object)
    out = {}
    for h, df in hojas.items():
        df = df.where(df.notna(), None)
        out[str(h)] = df.values.tolist()
    return out


def detectar_encabezado(aoa) -> int:
    mejor, bs = 0, -1
    for i, r in enumerate(aoa[:25]):
        t = sum(1 for c in r if isinstance(c, str) and c.strip())
        hit = 5 if any(re.search(p, str(c or "").strip(), re.I) for c in r for p in FIELDS[0][2]) else 0
        if t + hit > bs:
            bs, mejor = t + hit, i
    return mejor


def adivinar_columnas(encabezados) -> dict[str, int]:
    h = [str(c or "").strip() for c in encabezados]
    usados, mapa = set(), {}
    for k, _, pats in FIELDS:
        idx = -1
        for p in pats:
            idx = next((j for j, c in enumerate(h) if c and j not in usados and re.search(p, c, re.I)), -1)
            if idx >= 0:
                break
        mapa[k] = idx
        if idx >= 0:
            usados.add(idx)
    return mapa


def unir_excels(partes):
    """Une varios Excel de fábrica (p. ej. sede 173 y Colisión) en una sola tabla.

    partes: lista de (filas, fila_encabezado, mapa_de_columnas) de cada archivo.
    Devuelve (filas_unidas, 0, mapa) listo para comparar_fabrica.
    """
    claves = [k for k, _, _ in FIELDS]
    out = [claves[:]]
    for aoa, hd, mapa in partes:
        for row in aoa[hd + 1:]:
            out.append([row[mapa[k]] if mapa.get(k, -1) >= 0 and mapa[k] < len(row) else None for k in claves])
    mapa_u = {k: (i if any(m.get(k, -1) >= 0 for _, _, m in partes) else -1) for i, k in enumerate(claves)}
    return out, 0, mapa_u


def comparar_fabrica(rows: dict[str, dict], aoa, header: int, mapa: dict, modo: str = "pr") -> dict:
    """Compara los pendientes del tablero con el Excel de fábrica. No guarda nada."""
    hoy_iso = hoy()
    key = (lambda p, r: clave(p, r)) if modo == "pr" else (lambda p, r: norm_ref(r))
    col = lambda row, k: row[mapa[k]] if mapa.get(k, -1) >= 0 and mapa[k] < len(row) else None
    fac = {}
    for row in aoa[header + 1:]:
        ref = col(row, "ref")
        if not norm_ref(ref):
            continue
        ped = col(row, "pedido") if mapa.get("pedido", -1) >= 0 else ""
        if modo == "pr" and not norm_ped(ped):
            continue
        k = key(ped, ref)
        eta_raw = col(row, "eta")
        item = {"ref": str(ref).strip(), "pedido": str(norm_ped(ped) or ped or "").strip(),
                "eta": to_iso(eta_raw), "etaRaw": str(eta_raw if eta_raw is not None else "").strip(),
                "cant": to_num(col(row, "cant")), "estadoRaw": str(col(row, "estado") or "").strip(),
                "desc": str(col(row, "desc") or "").strip(), "fecha": to_iso(col(row, "fecha"))}
        if k in fac:
            cur = fac[k]
            if item["cant"] is not None:
                cur["cant"] = (cur["cant"] or 0) + item["cant"]
            cur["eta"] = cur["eta"] or item["eta"]
        else:
            fac[k] = item

    todas = {key(r.get("pedido"), r.get("ref")) for r in rows.values()}
    patch, cambios, faltantes = {}, [], []
    coinc = sin_eta = 0
    desconocidos = set()
    for rid, r in rows.items():
        if r.get("estado") not in OPEN:
            continue
        f = fac.get(key(r.get("pedido"), r.get("ref")))
        base = {"n": r.get("n"), "pedido": r.get("pedido"), "ref": r.get("ref"), "desc": r.get("desc")}
        if f:
            coinc += 1
            ch = {}
            sin = mapa.get("eta", -1) >= 0 and not f["eta"] and bool(f["etaRaw"])
            if sin:
                sin_eta += 1
            if mapa.get("eta", -1) >= 0 and sin != bool(r.get("sinEtd")):
                ch["sinEtd"] = sin
            if f["eta"] and f["eta"] != r.get("eta"):
                ch["eta"] = f["eta"]
                cambios.append({**base, "campo": "ETA", "antes": fmt_d(r.get("eta")), "despues": fmt_d(f["eta"])})
            if f["cant"] is not None and f["cant"] != r.get("cantFab"):
                ch["cantFab"] = f["cant"]
                if r.get("cantFab") is not None:
                    cambios.append({**base, "campo": "Cant. fábrica", "antes": r.get("cantFab"), "despues": f["cant"]})
            if f["estadoRaw"]:
                e = map_estado(f["estadoRaw"])
                if e and e != r.get("estado"):
                    ch["estado"] = e
                    if e == "Llegó" and not r.get("llegada"):
                        ch["llegada"] = hoy_iso
                    cambios.append({**base, "campo": "Estado", "antes": r.get("estado"), "despues": e})
                elif not e:
                    desconocidos.add(f["estadoRaw"])
            if r.get("revisar"):
                ch["revisar"] = False
                ch["revisarDesde"] = None
            campos = [c for c in ("eta", "estado") if c in ch]
            if "cantFab" in ch and r.get("cantFab") is not None:
                campos.append("cantFab")
            if campos:
                ch["cambio"] = {"fecha": hoy_iso, "campos": campos,
                                "etaAntes": fmt_d(r.get("eta")) if "eta" in ch else None,
                                "cantAntes": r.get("cantFab") if "cantFab" in campos else None,
                                "estadoAntes": r.get("estado") if "estado" in ch else None}
            if ch:
                patch[rid] = ch
        else:
            faltantes.append({**base, "cant": r.get("cant"), "eta": r.get("eta"), "cliente": r.get("cliente"),
                              "resp": r.get("resp"), "estado": r.get("estado"),
                              "desde": r.get("revisarDesde") or hoy_iso})
            if not r.get("revisar"):
                patch[rid] = {"revisar": True, "revisarDesde": hoy_iso}
    nuevos = [{"pedido": f["pedido"], "ref": f["ref"], "desc": f["desc"], "cant": f["cant"], "eta": f["eta"],
               "fecha": f["fecha"]} for k, f in fac.items() if k not in todas]
    return {"en_fabrica": len(fac), "coinciden": coinc, "sin_eta": sin_eta, "cambios": cambios,
            "faltantes": faltantes, "nuevos": nuevos, "patch": patch, "desconocidos": sorted(desconocidos)[:8]}


CAMPOS_PEDIDO = ("cliente", "canal", "resp")


def datos_por_pedido(rows: dict[str, dict]) -> dict[str, dict]:
    """Para cada pedido, el cliente/canal/responsable cuando todas sus filas coinciden (un solo valor)."""
    vals: dict[str, dict[str, set]] = {}
    for r in rows.values():
        p = norm_ped(r.get("pedido"))
        if not p:
            continue
        for k in CAMPOS_PEDIDO:
            v = str(r.get(k) or "").strip()
            if v:
                vals.setdefault(p, {}).setdefault(k, set()).add(v)
    return {p: {k: next(iter(s)) for k, s in d.items() if len(s) == 1} for p, d in vals.items()}


def completar_fila(r: dict, por_pedido: dict) -> dict:
    """Campos vacíos de cliente/canal/responsable que se pueden copiar de otra fila del mismo pedido."""
    conocidos = por_pedido.get(norm_ped(r.get("pedido")), {})
    return {k: conocidos[k] for k in CAMPOS_PEDIDO if not str(r.get(k) or "").strip() and k in conocidos}


def completar_desde_pedidos(rows: dict[str, dict]) -> dict[str, dict]:
    """Patch para todas las filas a las que les falta cliente/canal/responsable y su pedido lo tiene en otra fila."""
    pp = datos_por_pedido(rows)
    patch = {}
    for rid, r in rows.items():
        f = completar_fila(r, pp)
        if f:
            patch[rid] = f
    return patch


def fila_nueva_desde_fabrica(x: dict) -> dict:
    return {"pedido": str(x.get("pedido") or ""), "fecha": x.get("fecha"), "ref": str(x.get("ref") or ""),
            "desc": x.get("desc") or "", "cant": x.get("cant"), "cantFab": x.get("cant"), "eta": x.get("eta"),
            "sinEtd": not x.get("eta"), "canal": "", "cliente": "", "resp": "", "estado": "Pendiente",
            "nota": "", "llegada": None, "agregado": hoy()}


def aplicar_carga(res: dict, archivo: str, modo: str, rows: dict | None = None) -> dict:
    guardar_cambios(res["patch"])
    if res["nuevos"]:
        pp = datos_por_pedido(rows or {})
        nuevas = []
        for x in res["nuevos"]:
            f = fila_nueva_desde_fabrica(x)
            f.update(completar_fila(f, pp))  # cliente/canal/responsable del mismo pedido
            nuevas.append(f)
        agregar_repuestos(nuevas)
    ts = dt.datetime.now().isoformat(timespec="seconds")
    n = lambda k: sum(1 for c in res["cambios"] if c["campo"] == k)
    doc = {"ts": ts, "fecha": hoy(), "archivo": archivo, "modo": modo,
           "resumen": {"enFabrica": res["en_fabrica"], "coinciden": res["coinciden"],
                       "faltantes": len(res["faltantes"]), "nuevos": len(res["nuevos"]),
                       "eta": n("ETA"), "cant": n("Cant. fábrica"), "estado": n("Estado")},
           "faltantes": res["faltantes"], "cambios": res["cambios"], "nuevos": res["nuevos"]}
    cid = "c" + re.sub(r"\D", "", ts)
    _guardar("cargas", cid, doc)
    set_config(actualizado=hoy(), ultimaCarga=cid)
    doc["id"] = cid
    return doc


# ------------------------------------------------------ Lista de empaque
def leer_lista_empaque(data: bytes) -> dict:
    """Lee el PDF 'LISTA DE EMPAQUE' de SAP: Caja, Tipo caja, Producto, Descripción, Item, Pedido, Cantidad, Peso."""
    import pdfplumber
    out, entrega, fecha, desc_x = [], "", "", None
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False)
            lineas = []
            for w in words:
                L = next((l for l in lineas if abs(l["y"] - w["top"]) <= 2.5), None)
                if not L:
                    L = {"y": w["top"], "w": []}
                    lineas.append(L)
                L["w"].append(w)
            lineas.sort(key=lambda l: l["y"])
            for L in lineas:
                ws = sorted(L["w"], key=lambda w: w["x0"])
                celdas = []  # une palabras cercanas en una misma celda
                for w in ws:
                    if celdas and w["x0"] - celdas[-1]["x1"] < 4.5:
                        celdas[-1]["s"] += " " + w["text"]
                        celdas[-1]["x1"] = w["x1"]
                    else:
                        celdas.append({"s": w["text"], "x": w["x0"], "x1": w["x1"]})
                txt = " ".join(c["s"] for c in celdas)
                if not entrega:
                    m = re.search(r"ENTREGA\s+(\d{5,})", txt)
                    if m:
                        entrega = m[1]
                if not fecha:
                    m = re.search(r"Fecha:\s*(\d{2})\.(\d{2})\.(\d{4})", txt)
                    if m:
                        fecha = f"{m[3]}-{m[2]}-{m[1]}"
                a = celdas
                if a and re.fullmatch(r"\d{8,}", a[0]["s"]) and len(a) >= 7 and re.fullmatch(r"\d+", a[-2]["s"]):
                    n = len(a)
                    mid = a[1:n - 4]
                    out.append({"caja": a[0]["s"], "tipo": mid[0]["s"] if mid else "",
                                "prod": mid[1]["s"] if len(mid) > 1 else "",
                                "desc": " ".join(c["s"] for c in mid[2:]), "item": a[n - 4]["s"],
                                "pedido": a[n - 3]["s"], "cant": int(a[n - 2]["s"])})
                    if len(mid) > 2:
                        desc_x = mid[2]["x"]
                elif out and desc_x is not None and len(a) == 1 and abs(a[0]["x"] - desc_x) < 20 \
                        and not re.search("total", txt, re.I):
                    out[-1]["desc"] += " " + a[0]["s"]
    agg = {}
    for it in out:
        k = clave(it["pedido"], it["prod"])
        if k in agg:
            agg[k]["cant"] += it["cant"]
            if it["caja"] not in agg[k]["cajas"]:
                agg[k]["cajas"].append(it["caja"])
        else:
            agg[k] = {**it, "cajas": [it["caja"]]}
    return {"entrega": entrega, "fecha": fecha, "lineas": len(out), "unidades": sum(i["cant"] for i in out),
            "items": list(agg.values())}


def clasificar_empaque(rows: dict[str, dict], pk: dict) -> dict:
    por_clave = {}
    for rid, r in rows.items():
        por_clave.setdefault(clave(r.get("pedido"), r.get("ref")), []).append((rid, r))
    res = {"llegan": [], "yaLlego": [], "noBo": []}
    for it in pk["items"]:
        base = {"pedido": it["pedido"], "ref": it["prod"], "desc": it["desc"], "cant": it["cant"],
                "cajas": ", ".join(it["cajas"])}
        rs = por_clave.get(clave(it["pedido"], it["prod"]))
        if not rs:
            res["noBo"].append(base)
            continue
        rid, r = next(((i, x) for i, x in rs if x.get("estado") in OPEN), rs[0])
        if r.get("estado") in OPEN:
            ya = pk["entrega"] in (r.get("empaques") or [])
            prev = r.get("recibido") or 0
            tot = prev if ya else prev + it["cant"]
            pedida = r.get("cant") if r.get("cant") is not None else it["cant"]
            res["llegan"].append({**base, "id": rid, "pedida": pedida, "recibido": tot,
                                  "estadoAntes": estado_mostrado(r), "nuevo": "Llegó" if tot >= pedida else "Parcial",
                                  "ya": ya, "cliente": r.get("cliente"), "resp": r.get("resp")})
        else:
            res["yaLlego"].append({**base, "estado": r.get("estado"), "llegada": r.get("llegada"),
                                   "cliente": r.get("cliente")})
    return res


def registrar_empaque(rows, pk: dict, res: dict, archivo: str) -> dict:
    patch = {}
    for x in res["llegan"]:
        if x["ya"] or x["id"] not in rows:
            continue
        r = rows[x["id"]]
        f = {"recibido": x["recibido"], "estado": x["nuevo"],
             "empaques": list(r.get("empaques") or []) + [pk["entrega"] or archivo],
             "ultimaEntrega": pk["fecha"] or hoy()}
        if x["nuevo"] == "Llegó" and not r.get("llegada"):
            f["llegada"] = pk["fecha"] or hoy()
        if r.get("revisar"):
            f["revisar"] = False
            f["revisarDesde"] = None
        patch[x["id"]] = f
    guardar_cambios(patch)
    ts = dt.datetime.now().isoformat(timespec="seconds")
    doc = {"entrega": pk["entrega"], "fecha": pk["fecha"] or None, "archivo": archivo, "ts": ts,
           "aplicada": hoy(), "lineas": pk["lineas"], "unidades": pk["unidades"],
           "resumen": {"llegan": len(res["llegan"]), "yaLlego": len(res["yaLlego"]), "noBo": len(res["noBo"])},
           "llegan": [{k: v for k, v in x.items() if k != "id"} for x in res["llegan"]],
           "yaLlego": res["yaLlego"], "noBo": res["noBo"]}
    eid = "E" + (re.sub(r"\W", "", pk["entrega"] or "") or "sin") + "-" + re.sub(r"\D", "", ts)
    _guardar("empaques", eid, doc)
    return doc


# ------------------------------------------------------ Excel de salida
def _xlsx(hojas: dict[str, tuple[list[str], list[list]]], rojos: dict | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    for nombre, (head, filas) in hojas.items():
        ws = wb.create_sheet(nombre[:31])
        ws.append(head)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="16191F")
        for f in filas:
            ws.append([dt.date.fromisoformat(v) if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)
                       else v for v in f])
        for col in ws.columns:
            ancho = max(len(str(c.value or "")) for c in col[:300])
            ws.column_dimensions[col[0].column_letter].width = min(max(10, ancho + 2), 45)
            for c in col:
                if isinstance(c.value, dt.date):
                    c.number_format = "DD/MM/YYYY"
        for fila, col in (rojos or {}).get(nombre, ()):
            ws.cell(row=fila, column=col).font = Font(color="D32F2F", bold=True)
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def excel_tablero(rows: dict[str, dict]) -> bytes:
    head = ["#", "PEDIDO", "FECHA PEDIDO", "REFERENCIA", "DESCRIPCIÓN", "CANTIDAD", "CANT. FÁBRICA", "ETA",
            "CANAL", "CLIENTE", "RESPONSABLE", "FECHA REAL LLEGADA", "LEAD TIME", "ESTADO", "NOTA"]
    filas = []
    for r in sorted(rows.values(), key=lambda r: r.get("n") or 0):
        lt = lead_time(r.get("fecha"), r.get("llegada"))
        filas.append([r.get("n"), r.get("pedido"), r.get("fecha"), r.get("ref"), r.get("desc"), r.get("cant"),
                      r.get("cantFab"), eta_mostrada(r)[0], r.get("canal"), r.get("cliente"), r.get("resp"),
                      r.get("llegada"), "-" if lt is None else lt, estado_mostrado(r), r.get("nota") or ""])
    rojos = {(i + 2, 8) for i, r in enumerate(sorted(rows.values(), key=lambda r: r.get("n") or 0))
             if eta_mostrada(r)[1]}
    return _xlsx({"Tablero": (head, filas)}, rojos={"Tablero": rojos})


def excel_carga(c: dict) -> bytes:
    return _xlsx({
        "No aparecen": (["#", "PEDIDO", "REFERENCIA", "DESCRIPCIÓN", "CANTIDAD", "ETA", "CLIENTE", "RESPONSABLE",
                         "ESTADO", "SIN APARECER DESDE"],
                        [[f.get("n"), f.get("pedido"), f.get("ref"), f.get("desc"), f.get("cant"), f.get("eta"),
                          f.get("cliente"), f.get("resp"), f.get("estado"), f.get("desde")] for f in c.get("faltantes", [])]),
        "Cambios": (["#", "PEDIDO", "REFERENCIA", "DESCRIPCIÓN", "CAMPO", "ANTES", "AHORA"],
                    [[x.get("n"), x.get("pedido"), x.get("ref"), x.get("desc"), x.get("campo"), x.get("antes"),
                      x.get("despues")] for x in c.get("cambios", [])]),
        "Nuevos agregados": (["PEDIDO", "REFERENCIA", "DESCRIPCIÓN", "CANTIDAD", "ETA"],
                             [[x.get("pedido"), x.get("ref"), x.get("desc"), x.get("cant"), x.get("eta")]
                              for x in c.get("nuevos", [])]),
    })


def excel_empaque(doc: dict) -> bytes:
    return _xlsx({
        "Del BO que llegan": (["PEDIDO", "REFERENCIA", "DESCRIPCIÓN", "LLEGA", "RECIBIDO", "PEDIDA", "ESTADO ANTES",
                               "QUEDA EN", "CLIENTE", "RESPONSABLE"],
                              [[x.get("pedido"), x.get("ref"), x.get("desc"), x.get("cant"), x.get("recibido"),
                                x.get("pedida"), x.get("estadoAntes"), x.get("nuevo"), x.get("cliente"), x.get("resp")]
                               for x in doc.get("llegan", [])]),
        "Ya llegados": (["PEDIDO", "REFERENCIA", "DESCRIPCIÓN", "LLEGA", "ESTADO"],
                        [[x.get("pedido"), x.get("ref"), x.get("desc"), x.get("cant"), x.get("estado")]
                         for x in doc.get("yaLlego", [])]),
        "No son del BO": (["PEDIDO", "REFERENCIA", "DESCRIPCIÓN", "LLEGA", "CAJA"],
                          [[x.get("pedido"), x.get("ref"), x.get("desc"), x.get("cant"), x.get("cajas")]
                           for x in doc.get("noBo", [])]),
    })


# ------------------------------------------------------ Reporte por canal (PDF)
CANAL_RGB = {"colision": (36, 99, 196), "boutique": (140, 145, 153), "mostrador": (46, 158, 70),
             "stock": (255, 255, 255), "mecanica": (211, 47, 47), "otro": (93, 101, 115)}


def canal_nombre(r) -> str:
    return r.get("canal") or "Sin canal"


def canales_presentes(rows) -> list[str]:
    cs = sorted({canal_nombre(r) for r in rows.values()}, key=lambda c: (c == "Sin canal", fold(c)))
    return cs


def filas_reporte(rows, canal, alcance) -> list[dict]:
    def ok(r):
        if alcance == "todos":
            return True
        if alcance == "vencida":
            return cat(r) == "vencida"
        return r.get("estado") in OPEN
    lst = [r for r in rows.values() if canal_nombre(r) == canal and ok(r)]
    return sorted(lst, key=lambda r: (r.get("eta") or "9999", str(r.get("pedido"))))


def pdf_canal(rows, canal: str, alcance: str, actualizado: str | None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    enc = StandardEncryption("", ownerPassword=secrets.token_hex(10), canPrint=1, canModify=0, canCopy=0,
                             canAnnotate=0)
    buf = io.BytesIO()
    W, H = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=28, rightMargin=28, topMargin=24,
                            bottomMargin=34, encrypt=enc, title=f"Backorder canal {canal}", author="Yokomotor 173")
    alc_txt = {"todos": "Todos los estados", "vencida": "Solo ETA vencida"}.get(alcance, "Solo backorder (Pendiente + Parcial)")
    cs = canales_presentes(rows) if canal == "__all" else [canal]
    cel = ParagraphStyle("c", fontName="Helvetica", fontSize=7.3, leading=8.8)
    story, primero = [], True
    est_color = {"Alerta": (180, 35, 24), "Revisar": (161, 92, 0), "Sin ETD": (47, 90, 168), "Llegó": (31, 122, 77),
                 "Cancelado": (120, 120, 120)}
    for c in cs:
        lst = filas_reporte(rows, c, alcance)
        if not lst:
            continue
        if not primero:
            story.append(PageBreak())
        primero = False
        k = "otro" if c == "Sin canal" else canal_key(c)
        rgb = colors.Color(*(v / 255 for v in CANAL_RGB[k]))
        tinta = colors.Color(0.1, 0.1, 0.1) if k == "stock" else colors.white
        tit = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=17, textColor=tinta, leading=20)
        sub = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, textColor=tinta, leading=11)
        banda = Table([[Paragraph(f"Backorder Yokomotor 173 · Canal {c}", tit)],
                       [Paragraph(f"Generado el {fmt_d(hoy())} · Última actualización de fábrica: "
                                  f"{fmt_d(actualizado) or '—'} · {alc_txt}", sub)]], colWidths=[W - 56])
        banda.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), rgb), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                                   ("TOPPADDING", (0, 0), (-1, 0), 10), ("BOTTOMPADDING", (0, -1), (-1, -1), 9)]))
        story += [banda, Spacer(1, 10)]
        cnt = {"aldia": 0, "sinetd": 0, "vencida": 0, "revisar": 0, "llego": 0, "otro": 0}
        for r in lst:
            cnt[cat(r)] += 1
        resumen = [("TOTAL", len(lst), (30, 30, 30)), ("AL DÍA", cnt["aldia"], (31, 122, 77)),
                   ("SIN ETD", cnt["sinetd"], (47, 90, 168)), ("ETA VENCIDA", cnt["vencida"], (180, 35, 24)),
                   ("NO APARECEN EN FÁBRICA", cnt["revisar"], (161, 92, 0))]
        if alcance == "todos":
            resumen.append(("LLEGARON", cnt["llego"], (31, 122, 77)))
        num = [Paragraph(f'<font color="#{"%02x%02x%02x" % col}" size="16"><b>{v:,}</b></font>'.replace(",", "."),
                         ParagraphStyle("n", leading=18)) for _, v, col in resumen]
        lab = [Paragraph(t, ParagraphStyle("l", fontName="Helvetica", fontSize=7, textColor=colors.grey))
               for t, _, _ in resumen]
        st = Table([num, lab], colWidths=[118] * len(resumen), hAlign="LEFT")
        st.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        story += [st, Spacer(1, 10)]
        head = ["Pedido", "Fecha pedido", "Referencia", "Descripción", "Cant.", "Cant. fáb.", "ETA", "Cliente",
                "Responsable", "Estado"]
        data = [head]
        estilos = []
        for i, r in enumerate(lst, start=1):
            em = estado_mostrado(r)
            eta_f, es_calc = eta_mostrada(r)
            eta = fmt_d(eta_f) if eta_f else ("Sin ETD" if cat(r) == "sinetd" else "")
            data.append([r.get("pedido") or "", fmt_d(r.get("fecha")), r.get("ref") or "",
                         Paragraph(str(r.get("desc") or ""), cel), "" if r.get("cant") is None else r.get("cant"),
                         "" if r.get("cantFab") is None else r.get("cantFab"), eta,
                         Paragraph(str(r.get("cliente") or ""), cel), Paragraph(str(r.get("resp") or ""), cel), em])
            colr = next((v for k2, v in est_color.items() if em.startswith(k2)), None)
            if colr:
                estilos.append(("TEXTCOLOR", (9, i), (9, i), colors.Color(*(v / 255 for v in colr))))
            if es_calc:  # ETA calculada en rojo; la de Toyota en negro
                estilos += [("TEXTCOLOR", (6, i), (6, i), colors.Color(211 / 255, 47 / 255, 47 / 255)),
                            ("FONTNAME", (6, i), (6, i), "Helvetica-Bold")]
            elif eta == "Sin ETD":
                estilos.append(("TEXTCOLOR", (6, i), (6, i), colors.Color(47 / 255, 90 / 255, 168 / 255)))
        t = Table(data, colWidths=[48, 56, 80, 175, 32, 42, 54, 130, 92, 77], repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rgb), ("TEXTCOLOR", (0, 0), (-1, 0), tinta),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 7.3),
            ("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold"), ("FONTNAME", (9, 1), (9, -1), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(.965, .97, .975)]),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.Color(.86, .87, .89)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN", (4, 1), (5, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3), *estilos]))
        story.append(t)
    if not story:
        story.append(Paragraph("No hay repuestos para ese canal con ese filtro.", cel))

    def pie(canv, d):
        canv.saveState()
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(colors.grey)
        canv.drawString(28, 16, "Documento generado desde el Tablero Backorder. Protegido contra edición.")
        canv.drawRightString(W - 28, 16, f"Página {d.page}")
        canv.restoreState()

    doc.build(story, onFirstPage=pie, onLaterPages=pie)
    return buf.getvalue()
