"""Tablero Backorder Yokomotor 173 — interfaz web (Streamlit).

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

import logica as L

st.set_page_config(page_title="Tablero Backorder Yokomotor 173", page_icon="📦", layout="wide")


@st.cache_resource
def _iniciar():
    L.iniciar_db()
    return True


try:
    _iniciar()
except Exception as e:  # p. ej. clave de Supabase mal escrita
    st.error("No se pudo conectar con la base de datos. Revisa DATABASE_URL en los secretos de la app "
             f"(Settings → Secrets).\n\nDetalle: {type(e).__name__}: {e}")
    st.stop()

# ------------------------------------------------------------------ estilos
st.markdown("""
<style>
.block-container{padding-top:1.4rem;max-width:1500px}
h1{font-size:1.9rem!important;text-transform:uppercase;letter-spacing:.01em;margin-bottom:0!important}
.meta{color:#5d6573;font-size:.92rem;margin:.1rem 0 .6rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:.4rem 0 .6rem}
.kpi{border:1px solid #d3d7de;border-radius:6px;padding:10px 14px;background:#fff}
.kpi .k{font-family:monospace;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#5d6573}
.kpi .v{font-size:30px;font-weight:700;line-height:1.1}
.kpi .s{font-size:12.5px;color:#5d6573}
.leyenda{font-size:13px;color:#5d6573;display:flex;gap:16px;flex-wrap:wrap;margin:.2rem 0}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:5px}
</style>""", unsafe_allow_html=True)

# Colores por canal según los parámetros de la empresa:
# Colisión azul · Boutique gris · Mostrador verde · Repuestos Stock Almacén blanco · Mecánica rojo
TINTE = {"colision": "#d4e3f8", "boutique": "#e4e6e9", "mostrador": "#d6efd9", "stock": "#ffffff",
         "mecanica": "#f8d4d4", "otro": ""}
CHIP = {"colision": "#2463c4", "boutique": "#8c9199", "mostrador": "#2e9e46", "stock": "#ffffff",
        "mecanica": "#d32f2f", "otro": "#5d6573"}
NUEVO_BG, UPD_BG = "#e6dcfa", "#ffe98a"  # nuevos morado, actualizados por fábrica amarillo
EST_COLOR = {"Alerta": "#b42318", "Revisar": "#a15c00", "Sin ETD": "#2f5aa8", "Llegó": "#1f7a4d",
             "Parcial": "#2f5aa8", "Cancelado": "#7a7a7a", "Pendiente": "#a15c00"}
ENVIOS = {"": "Sin calcular", "28": "Aéreo (28 días)", "66": "Marítimo (66 días)"}


# ------------------------------------------------------------------ acceso
def leer_configuracion() -> dict:
    p = Path(__file__).with_name("configuracion.txt")
    out = {}
    if p.exists():
        for linea in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.split("=", 1)
                out[k.strip().upper()] = v.strip()
    return out


CONF = leer_configuracion()
try:  # en Streamlit Community Cloud la clave va en los secretos de la app
    if st.secrets.get("CLAVE"):
        CONF["CLAVE"] = str(st.secrets["CLAVE"])
except Exception:
    pass
if CONF.get("CLAVE") and not st.session_state.get("ok"):
    st.title("Tablero Backorder · Yokomotor 173")
    clave = st.text_input("Clave de acceso", type="password")
    if st.button("Entrar", type="primary"):
        if clave == CONF["CLAVE"]:
            st.session_state.ok = True
            st.rerun()
        else:
            st.error("La clave no es correcta. Pídesela a quien administra el tablero.")
    st.stop()


# ------------------------------------------------------------------ datos
def fecha(s):
    return dt.date.fromisoformat(s[:10]) if s else None


def iso(d):
    return d.isoformat() if d else None


# Los datos se guardan en memoria unos segundos para que la página responda rápido;
# después de cada cambio se vuelven a leer (refrescar).
@st.cache_data(ttl=20, show_spinner=False)
def _rows():
    return L.cargar_repuestos()


@st.cache_data(ttl=20, show_spinner=False)
def _cfg():
    return L.config()


@st.cache_data(ttl=60, show_spinner=False)
def _historial():
    return L.cargas(), L.empaques()


def refrescar():
    _rows.clear()
    _cfg.clear()
    _historial.clear()


rows = _rows()
cfg = _cfg()
HOY = L.hoy()

if not rows:
    st.title("Tablero Backorder · Yokomotor 173")
    st.info("El tablero está vacío. Si es la primera vez que lo abres, sube el archivo de datos inicial "
            "(**backorder_datos.json**) o un respaldo descargado desde la pestaña Reportes.")
    ini = st.file_uploader("Archivo de datos (.json)", type=["json"])
    if ini and st.button("Cargar datos", type="primary"):
        try:
            n = L.importar_respaldo(ini.getvalue())
            refrescar()
            st.success(f"Se cargaron {n:,} repuestos.".replace(",", "."))
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo cargar el archivo: {e}")
    if st.button("Empezar con el tablero vacío"):
        L.agregar_repuestos([{"pedido": "", "ref": "EJEMPLO", "desc": "Repuesto de ejemplo, puedes borrarlo",
                              "estado": "Pendiente", "fecha": HOY}])
        refrescar()
        st.rerun()
    st.stop()
for k in ("tabla_v", "up_v", "pk_v"):
    st.session_state.setdefault(k, 0)

# ------------------------------------------------------------------ encabezado
st.markdown("<div style='font-family:monospace;font-size:12px;letter-spacing:.08em;color:#5d6573'>"
            "BACKORDER DE REPUESTOS</div>", unsafe_allow_html=True)
st.title("Tablero Backorder · Yokomotor 173")
st.markdown(f"<div class='meta'>Fecha actualización: <b>{L.fmt_d(cfg.get('actualizado')) or '—'}</b>"
            f" &nbsp;·&nbsp; Total en tablero: <b>{len(rows):,}</b></div>".replace(",", "."), unsafe_allow_html=True)

cnt = {"aldia": 0, "sinetd": 0, "vencida": 0, "revisar": 0, "llego": 0, "otro": 0}
bo = lt_sum = lt_n = 0
for r in rows.values():
    c = L.cat(r, HOY)
    cnt[c] += 1
    if r.get("estado") in L.OPEN:
        bo += 1
    if c == "llego":
        lt = L.lead_time(r.get("fecha"), r.get("llegada"))
        if lt is not None and lt >= 0:
            lt_sum += lt
            lt_n += 1
nf = lambda n: f"{n:,}".replace(",", ".")
tarjetas = [("Todos los estados", len(rows), "#16191f", f"Backorder {nf(bo)} (Pendiente + Parcial)"),
            ("Al día", cnt["aldia"], "#1f7a4d", "ETA confirmada, todavía no vence"),
            ("Sin ETD", cnt["sinetd"], "#2f5aa8", "Fábrica: “Pedido sin ETD”"),
            ("ETA vencida", cnt["vencida"], "#b42318", "Estado Alerta"),
            ("No aparecen en fábrica", cnt["revisar"], "#a15c00", "Estado Revisar"),
            ("Llegaron", cnt["llego"], "#16191f", f"Lead time prom. {round(lt_sum / lt_n) if lt_n else '—'} días hábiles")]
st.markdown("<div class='kpis'>" + "".join(
    f"<div class='kpi'><div class='k'>{k}</div><div class='v' style='color:{c}'>{nf(v)}</div><div class='s'>{s}</div></div>"
    for k, v, c, s in tarjetas) + "</div>", unsafe_allow_html=True)

tab_t, tab_f, tab_e, tab_r, tab_h = st.tabs(["Tablero", "Subir Excel de fábrica", "Lista de empaque",
                                             "Reportes", "Actualizaciones"])


# ================================================================== edición
def _calc_eta():
    """La ETA calculada se muestra aparte; ya no reemplaza la ETA de Toyota."""
    return None


@st.dialog("Repuesto", width="large")
def dlg_repuesto(rid: str | None, pre: dict | None = None):
    r = rows.get(rid) if rid else (pre or {"estado": "Pendiente", "fecha": HOY, "canal": "Mostrador"})
    if st.session_state.get("e_init") != (rid or "nuevo"):
        st.session_state.e_init = rid or "nuevo"
        for k in ("pedido", "ref", "desc", "cliente", "resp", "nota"):
            st.session_state["e_" + k] = str(r.get(k) or "")
        for k in ("fecha", "eta", "llegada"):
            st.session_state["e_" + k] = fecha(r.get(k))
        for k in ("cant", "cantFab"):
            st.session_state["e_" + k] = None if r.get(k) is None else float(r.get(k))
        st.session_state.e_envio = str(r.get("envio") or "")
        st.session_state.e_canal = r.get("canal") or ""
        st.session_state.e_estado = r.get("estado") or "Pendiente"
        st.session_state.e_revisar = bool(r.get("revisar"))
        st.session_state.e_borrar = False
    st.subheader(f"Editar repuesto #{r.get('n')}" if rid else "Nuevo repuesto")
    if r.get("revisar"):
        st.warning(f"No apareció en el Excel de fábrica desde el {L.fmt_d(r.get('revisarDesde'))}. "
                   "Revisa si llegó o se canceló y actualiza el estado.")
    c1, c2, c3, c4 = st.columns(4)
    c1.text_input("Pedido", key="e_pedido")
    c2.date_input("Fecha pedido", key="e_fecha", format="DD/MM/YYYY", on_change=_calc_eta,
                  min_value=dt.date(2015, 1, 1))
    c3.text_input("Referencia", key="e_ref")
    c4.number_input("Cantidad pedida", key="e_cant", min_value=0.0, step=1.0, format="%g")
    st.text_input("Descripción", key="e_desc")
    c1, c2, c3, c4 = st.columns(4)
    c1.number_input("Cantidad fábrica", key="e_cantFab", min_value=0.0, step=1.0, format="%g")
    c2.selectbox("Tipo de envío", list(ENVIOS), format_func=ENVIOS.get, key="e_envio", on_change=_calc_eta)
    c3.date_input("ETA Toyota (fábrica)", key="e_eta", format="DD/MM/YYYY", min_value=dt.date(2015, 1, 1))
    c4.date_input("Fecha real llegada", key="e_llegada", format="DD/MM/YYYY", min_value=dt.date(2015, 1, 1))
    if st.session_state.e_envio:
        base = st.session_state.e_fecha or dt.date.today()
        st.info(f"**ETA calculada:** {base + dt.timedelta(days=int(st.session_state.e_envio)):%d/%m/%Y}  "
                f"(fecha de pedido {base:%d/%m/%Y} + {st.session_state.e_envio} días calendario). "
                "Si el repuesto no tiene ETA de Toyota, en la tabla se muestra esta en rojo.")
    canales = sorted(set(L.CANALES_BASE) | {x.get("canal") for x in rows.values() if x.get("canal")})
    if st.session_state.e_canal and st.session_state.e_canal not in canales:
        canales.append(st.session_state.e_canal)
    c1, c2, c3 = st.columns(3)
    c1.selectbox("Canal", [""] + canales, key="e_canal", format_func=lambda x: x or "(sin canal)")
    c2.selectbox("Estado", L.ESTADOS, key="e_estado")
    resp = sorted({x.get("resp") for x in rows.values() if x.get("resp")})
    if st.session_state.e_resp and st.session_state.e_resp not in resp:
        resp.append(st.session_state.e_resp)
    c3.selectbox("Responsable", [""] + resp, key="e_resp", accept_new_options=True,
                 format_func=lambda x: x or "(sin responsable)")
    st.text_input("Cliente", key="e_cliente")
    st.text_area("Nota", key="e_nota", height=70)
    st.checkbox("Marcado para revisar", key="e_revisar")

    b1, b2, b3 = st.columns([1, 1, 3])
    if b1.button("Guardar", type="primary", width="stretch"):
        if not st.session_state.e_ref.strip():
            st.error("Escribe la referencia.")
            return
        v = {k: st.session_state["e_" + k].strip() for k in ("pedido", "ref", "desc", "cliente", "nota")}
        v["resp"] = (st.session_state.e_resp or "").strip()
        v.update(fecha=iso(st.session_state.e_fecha), eta=iso(st.session_state.e_eta),
                 llegada=iso(st.session_state.e_llegada), canal=st.session_state.e_canal,
                 estado=st.session_state.e_estado, envio=st.session_state.e_envio,
                 revisar=st.session_state.e_revisar)
        for k in ("cant", "cantFab"):
            x = st.session_state["e_" + k]
            v[k] = None if x is None else (int(x) if float(x).is_integer() else x)
        if not v["revisar"]:
            v["revisarDesde"] = None
        if v["estado"] == "Llegó" and not v["llegada"]:
            v["llegada"] = HOY
        # Sin ETD se quita cuando alguien escribe una ETA nueva
        if rid:
            v["sinEtd"] = False if (v["eta"] and v["eta"] != r.get("eta")) else bool(r.get("sinEtd"))
        else:
            v["sinEtd"] = bool(pre and pre.get("sinEtd")) and not v["eta"]
        # Si faltan cliente/canal/responsable y el pedido ya existe en otra fila, se copian de ahí
        v.update(L.completar_fila(v, L.datos_por_pedido({k: x for k, x in rows.items() if k != rid})))
        if rid:
            L.guardar_cambios({rid: v})
        else:
            if pre:
                v["agregado"] = pre.get("agregado")
            L.agregar_repuestos([{k: x for k, x in v.items() if x is not None}])
        refrescar()
        st.session_state.e_init = None
        st.session_state.tabla_v += 1
        st.session_state.aviso = "Cambios guardados" if rid else "Repuesto agregado"
        st.rerun()
    if b2.button("Cancelar", width="stretch"):
        st.session_state.e_init = None
        st.session_state.tabla_v += 1
        st.rerun()
    if rid:
        with b3:
            if st.checkbox("Quiero eliminar este repuesto", key="e_borrar"):
                if st.button("Sí, eliminar", type="secondary"):
                    L.borrar_repuesto(rid)
                    refrescar()
                    st.session_state.e_init = None
                    st.session_state.tabla_v += 1
                    st.session_state.aviso = "Repuesto eliminado"
                    st.rerun()


# ================================================================== tablero
with tab_t:
    if st.session_state.get("aviso"):
        st.toast(st.session_state.pop("aviso"))
    opciones = {"": f"Todos · {nf(len(rows))}", "aldia": f"Al día · {nf(cnt['aldia'])}",
                "sinetd": f"Sin ETD · {nf(cnt['sinetd'])}", "vencida": f"ETA vencida · {nf(cnt['vencida'])}",
                "revisar": f"No aparecen en fábrica · {nf(cnt['revisar'])}", "llego": f"Llegaron · {nf(cnt['llego'])}"}
    grupo = st.segmented_control("Ver", list(opciones), format_func=opciones.get, default="", key="grupo",
                                 label_visibility="collapsed") or ""
    f1, f2, f3, f4, f5 = st.columns([3, 1.6, 1.3, 1.6, 1.1])
    q = f1.text_input("Buscar", placeholder="Buscar referencia, pedido, cliente, descripción…",
                      label_visibility="collapsed")
    est_op = ["", "backorder", "Alerta", "Revisar", "Sin ETD", "Pendiente", "Parcial", "Llegó", "Cancelado"]
    est_lab = {"": "Todos los estados", "backorder": "Backorder (Pendiente + Parcial)", "Alerta": "Alerta (ETA vencida)",
               "Revisar": "Revisar (no aparece en fábrica)"}
    f_est = f2.selectbox("Estado", est_op, format_func=lambda x: est_lab.get(x, x), label_visibility="collapsed")
    canales = sorted(set(L.CANALES_BASE) | {r.get("canal") for r in rows.values() if r.get("canal")})
    VACIO = "__vacio__"
    f_can = f3.selectbox("Canal", ["", VACIO] + canales,
                         format_func=lambda x: "Todos los canales" if not x else
                         ("Vacío (sin canal)" if x == VACIO else x),
                         label_visibility="collapsed")
    resps = sorted({r.get("resp") for r in rows.values() if r.get("resp")})
    f_resp = f4.selectbox("Responsable", ["", VACIO] + resps,
                          format_func=lambda x: "Todos los responsables" if not x else
                          ("Vacío (sin responsable)" if x == VACIO else x),
                          label_visibility="collapsed")
    if f5.button("＋ Nuevo repuesto", width="stretch"):
        st.session_state.e_init = None
        dlg_repuesto(None)

    completar = L.completar_desde_pedidos(rows)
    if completar:
        b1, b2 = st.columns([5, 1.4])
        b1.info(f"**{nf(len(completar))} repuestos** no tienen cliente, canal o responsable, pero su mismo pedido ya "
                "los tiene en otra fila. Se pueden completar automáticamente (solo cuando todas las filas del pedido "
                "coinciden).")
        if b2.button("Completar datos", type="primary", width="stretch"):
            L.guardar_cambios(completar)
            refrescar()
            st.session_state.tabla_v += 1
            st.session_state.aviso = f"Se completaron {nf(len(completar))} repuestos"
            st.rerun()

    n_upd = sum(1 for r in rows.values() if L.campos_actualizados(r, cfg))
    n_new = sum(1 for r in rows.values() if L.es_nuevo(r, cfg))
    g1, g2, g3 = st.columns([1.2, 1.2, 5])
    solo_upd = g1.checkbox("Solo actualizados", disabled=not n_upd)
    solo_new = g2.checkbox("Solo nuevos", disabled=not n_new)
    g3.markdown(
        f"<div class='leyenda'><span><span class='sw' style='background:{UPD_BG};border:1px solid #9a7400'></span>"
        f"Amarillo: {nf(n_upd)} pedidos existentes actualizados en la carga del {L.fmt_d(cfg.get('actualizado'))}</span>"
        f"<span><span class='sw' style='background:{NUEVO_BG};border:1px solid #6d3fc0'></span>"
        f"Morado: {nf(n_new)} repuestos nuevos desde la fábrica</span>"
        f"<span><b style='color:#16191f'>ETA negra</b>: de Toyota · <b style='color:#d32f2f'>ETA roja</b>: calculada</span></div>", unsafe_allow_html=True)

    qf = L.fold(q)
    lista = []
    for rid, r in rows.items():
        em = L.estado_mostrado(r, HOY)
        c = L.cat(r, HOY)
        if grupo and c != grupo:
            continue
        if f_est == "backorder":
            if r.get("estado") not in L.OPEN:
                continue
        elif f_est and not em.startswith(f_est):
            continue
        if f_can == VACIO:
            if str(r.get("canal") or "").strip():
                continue
        elif f_can and r.get("canal") != f_can:
            continue
        if f_resp == VACIO:
            if str(r.get("resp") or "").strip():
                continue
        elif f_resp and r.get("resp") != f_resp:
            continue
        if solo_upd and not L.campos_actualizados(r, cfg):
            continue
        if solo_new and not L.es_nuevo(r, cfg):
            continue
        if qf:
            hay = L.fold(" ".join(str(r.get(k) or "") for k in ("ref", "pedido", "cliente", "desc", "resp", "nota")))
            if not all(t in hay for t in qf.split()) and L.norm_ref(q) not in L.norm_ref(r.get("ref")):
                continue
        lista.append((rid, r, em))
    lista.sort(key=lambda x: x[1].get("n") or 0)
    # La tabla se muestra por páginas para que cada clic responda rápido
    POR_PAG = 100
    total_f = len(lista)
    paginas = max(1, -(-total_f // POR_PAG))
    filtro_id = (grupo, q, f_est, f_can, f_resp, solo_upd, solo_new)
    if st.session_state.get("filtro_id") != filtro_id:
        st.session_state.filtro_id = filtro_id
        st.session_state.pagina = 1
    st.session_state.pagina = min(max(1, st.session_state.get("pagina", 1)), paginas)
    ini = (st.session_state.pagina - 1) * POR_PAG
    lista = lista[ini:ini + POR_PAG]

    ids = [x[0] for x in lista]
    df = pd.DataFrame([{
        "#": r.get("n"), "Pedido": r.get("pedido"), "Fecha pedido": fecha(r.get("fecha")), "Referencia": r.get("ref"),
        "Descripción": r.get("desc"), "Cant. pedida": r.get("cant"), "Cant. fábrica": r.get("cantFab"),
        "ETA": fecha(L.eta_mostrada(r)[0]), "Canal": r.get("canal") or "", "Cliente": r.get("cliente"),
        "Responsable": r.get("resp"), "Llegada": fecha(r.get("llegada")),
        "Lead time": L.lead_time(r.get("fecha"), r.get("llegada")), "Estado": em} for _, r, em in lista],
        columns=["#", "Pedido", "Fecha pedido", "Referencia", "Descripción", "Cant. pedida", "Cant. fábrica", "ETA",
                 "Canal", "Cliente", "Responsable", "Llegada", "Lead time", "Estado"])
    for col in ("Fecha pedido", "ETA", "Llegada"):
        df[col] = [d.strftime("%d/%m/%Y") if d else "" for d in df[col]]
    for col in ("Cant. pedida", "Cant. fábrica", "Lead time"):
        df[col] = [("" if v is None or v != v else f"{v:g}") for v in df[col]]

    COLS = list(df.columns)
    i_canal, i_eta, i_cf, i_est = (COLS.index(c) for c in ("Canal", "ETA", "Cant. fábrica", "Estado"))
    UPD_CSS = f"background-color:{UPD_BG};color:#6b4f00;font-weight:700;border:1px solid #c9a200"
    matriz = []
    for _, r, em in lista:
        k = L.canal_key(r.get("canal")) if r.get("canal") else None
        bg = NUEVO_BG if L.es_nuevo(r, cfg) else (TINTE.get(k, "") if k else "")
        fila = f"background-color:{bg};" if bg else ""
        f = [fila] * len(COLS)
        if k:
            f[i_canal] = (f"background-color:{CHIP[k]};color:#fff;font-weight:700" if k != "stock" else
                          "background-color:#fff;color:#16191f;font-weight:700;border:1px solid #16191f")
        c = L.cat(r, HOY)
        if c == "vencida":
            f[i_eta] = fila + "color:#16191f;font-weight:700"
        elif c == "revisar":
            f[i_eta] = fila + "color:#8a8f99;text-decoration:line-through"
        if L.eta_mostrada(r)[1]:  # ETA calculada (no viene de Toyota): rojo
            f[i_eta] = fila + "color:#d32f2f;font-weight:700"
        colr = next((v for kk, v in EST_COLOR.items() if em.startswith(kk)), "#16191f")
        f[i_est] = fila + f"color:{colr};font-weight:700"
        upd = L.campos_actualizados(r, cfg)
        if "eta" in upd:
            f[i_eta] = UPD_CSS
        if "cantFab" in upd:
            f[i_cf] = UPD_CSS
        if "estado" in upd:
            f[i_est] = UPD_CSS
        matriz.append(f)
    css_df = pd.DataFrame(matriz, index=df.index, columns=COLS) if matriz else pd.DataFrame("", index=df.index, columns=COLS)

    def estilos(_):
        return css_df

    def _pag(d):
        st.session_state.pagina += d
        st.session_state.tabla_v += 1

    rango = (f"{nf(ini + 1 if total_f else 0)}–{nf(ini + len(lista))} de {nf(total_f)} repuestos · "
             f"página {st.session_state.pagina} de {paginas}")
    st.caption(rango + " · haz clic en una fila para editarla")
    sel = st.dataframe(
        df.style.apply(estilos, axis=None).format(na_rep="", precision=0, thousands=""),
        hide_index=True,
        width="stretch", height=min(620, 38 + 35 * max(1, len(df))),
        on_select="rerun", selection_mode="single-row", key=f"tabla_{st.session_state.tabla_v}",
        column_config={
            "Descripción": st.column_config.TextColumn(width="medium"),
            "Cliente": st.column_config.TextColumn(width="medium"),
            "#": st.column_config.NumberColumn(width="small", format="%d"),

        })
    if paginas > 1:
        p1, p2, p3 = st.columns([5, 1, 1])
        p1.caption(rango)
        p2.button("‹ Anterior", on_click=_pag, args=(-1,), disabled=st.session_state.pagina <= 1, width="stretch")
        p3.button("Siguiente ›", on_click=_pag, args=(1,), disabled=st.session_state.pagina >= paginas,
                  width="stretch")
    filas_sel = sel.selection.rows if sel and sel.selection else []
    if filas_sel and filas_sel[0] < len(ids):
        dlg_repuesto(ids[filas_sel[0]])


# ================================================================== Excel de fábrica
def mostrar_carga(c: dict, key: str = ""):
    s = c.get("resumen", {})
    m = st.columns(5)
    m[0].metric("En el Excel de fábrica", s.get("enFabrica", 0))
    m[1].metric("Pendientes que aparecen", s.get("coinciden", 0))
    m[2].metric("No aparecen (Revisar)", s.get("faltantes", 0))
    m[3].metric("Cambios aplicados", (s.get("eta") or 0) + (s.get("cant") or 0) + (s.get("estado") or 0))
    m[4].metric("Nuevos agregados", s.get("nuevos", 0))
    st.markdown(f"**No aparecen en el Excel de fábrica ({len(c.get('faltantes', []))})** — quedaron en Revisar.")
    st.dataframe(pd.DataFrame(c.get("faltantes", []), columns=["pedido", "ref", "desc", "cant", "eta", "cliente", "resp"])
                 .rename(columns={"pedido": "Pedido", "ref": "Referencia", "desc": "Descripción", "cant": "Cant.",
                                  "eta": "ETA", "cliente": "Cliente", "resp": "Responsable"}),
                 hide_index=True, width="stretch", height=260)
    st.markdown(f"**Cambios aplicados ({len(c.get('cambios', []))})**")
    st.dataframe(pd.DataFrame(c.get("cambios", []), columns=["pedido", "ref", "campo", "antes", "despues"])
                 .rename(columns={"pedido": "Pedido", "ref": "Referencia", "campo": "Campo", "antes": "Antes",
                                  "despues": "Ahora"}).astype(str), hide_index=True, width="stretch", height=240)
    st.markdown(f"**Nuevos: agregados al tablero desde la fábrica ({len(c.get('nuevos', []))})**")
    st.dataframe(pd.DataFrame(c.get("nuevos", []), columns=["pedido", "ref", "desc", "cant", "eta"])
                 .rename(columns={"pedido": "Pedido", "ref": "Referencia", "desc": "Descripción", "cant": "Cant.",
                                  "eta": "ETA"}), hide_index=True, width="stretch", height=200)
    st.download_button("Descargar reporte (Excel)", L.excel_carga(c), f"Reporte backorder {c.get('fecha')}.xlsx",
                       key=f"dlc_{key}_{c.get('id')}")


with tab_f:
    if st.session_state.get("ultima_carga"):
        st.success("Tablero actualizado con el Excel de fábrica.")
        mostrar_carga(st.session_state.ultima_carga, "ult")
        if st.button("Subir otros archivos"):
            st.session_state.ultima_carga = None
            st.rerun()
    else:
        st.write("Sube **los Excel que envía la fábrica: el de la sede 173 y el de Colisión, juntos**. Se comparan "
                 "los repuestos **Pendiente** y **Parcial** contra los dos archivos a la vez, por **pedido + referencia**: "
                 "se actualizan ETA (ETA_DEALER), cantidad de fábrica y estado; los que no aparecen en ninguno quedan "
                 "en **Revisar**, y los repuestos de la fábrica que no están en el tablero se **agregan solos** como Pendiente.")
        archs = st.file_uploader("Excel de fábrica (puedes seleccionar los dos archivos a la vez)",
                                 type=["xlsx", "xls", "xlsm", "csv"], accept_multiple_files=True,
                                 key=f"up_{st.session_state.up_v}")
        partes, nombres_arch, error = [], [], False
        for n_a, arch in enumerate(archs or []):
            try:
                hojas = L.leer_excel(arch)
            except Exception:
                st.error(f"No se pudo leer «{arch.name}». Revisa que sea un Excel (.xlsx o .xls).")
                error = True
                continue
            hoja0 = list(hojas)[0]
            aoa0 = hojas[hoja0]
            hd0 = L.detectar_encabezado(aoa0)
            guess0 = L.adivinar_columnas(aoa0[hd0] if aoa0 else [])
            faltan = [lab for k, lab, _ in L.FIELDS if k in ("ref", "pedido", "eta") and guess0[k] < 0]
            with st.expander(f"Archivo {n_a + 1}: {arch.name}" + (" — revisa las columnas" if faltan else
                             " — columnas reconocidas"), expanded=bool(faltan)):
                c1, c2 = st.columns(2)
                hoja = c1.selectbox("Hoja", list(hojas), key=f"hoja_{n_a}_{arch.name}")
                aoa = hojas[hoja]
                hd = c2.number_input("Fila de encabezados", 1, max(1, len(aoa)), L.detectar_encabezado(aoa) + 1,
                                     key=f"hd_{n_a}_{arch.name}_{hoja}") - 1
                enc = aoa[hd] if aoa else []
                guess = L.adivinar_columnas(enc)
                nombres = ["— No usar —"] + [str(c or f"(Columna {i + 1})").strip() for i, c in enumerate(enc)]
                cols = st.columns(4)
                mapa = {}
                for i, (k, lab, _) in enumerate(L.FIELDS):
                    sel_i = cols[i % 4].selectbox(lab, range(len(nombres)), index=guess[k] + 1,
                                                  format_func=lambda j, nombres=nombres: nombres[j],
                                                  key=f"map_{n_a}_{arch.name}_{k}_{hoja}_{hd}")
                    mapa[k] = sel_i - 1
            if mapa["ref"] < 0:
                st.error(f"En «{arch.name}» elige la columna de la referencia para poder comparar.")
                error = True
                continue
            partes.append((aoa, hd, mapa))
            nombres_arch.append(arch.name)
        if partes and not error:
            aoa_u, hd_u, mapa_u = L.unir_excels(partes)
            todos_pedido = all(m["pedido"] >= 0 for _, _, m in partes)
            modo = st.selectbox("Comparar por", ["pr", "r"], index=0 if todos_pedido else 1,
                                format_func=lambda m: "Pedido + referencia" if m == "pr" else "Solo referencia")
            if len(partes) == 1:
                st.warning("Subiste un solo archivo. Si esta semana llegaron el de la sede 173 y el de Colisión, "
                           "súbelos **juntos**: si subes solo uno, los repuestos que están en el otro quedarán en Revisar.")
            res = L.comparar_fabrica(rows, aoa_u, hd_u, mapa_u, modo)
            st.markdown("#### Vista previa" + (f" (los {len(partes)} archivos juntos)" if len(partes) > 1 else ""))
            m = st.columns(6)
            m[0].metric("En los Excel de fábrica", res["en_fabrica"])
            m[1].metric("Pendientes que aparecen", res["coinciden"])
            m[2].metric("Pendientes que NO aparecen", len(res["faltantes"]))
            m[3].metric("ETAs que cambian", sum(1 for c in res["cambios"] if c["campo"] == "ETA"))
            m[4].metric("Cant. fábrica que cambian", sum(1 for c in res["cambios"] if c["campo"] == "Cant. fábrica"))
            m[5].metric("Nuevos que se agregan", len(res["nuevos"]))
            if res["sin_eta"]:
                st.info(f"{res['sin_eta']} pendientes aparecen en la fábrica sin fecha (por ejemplo “PEDIDO SIN ETD”); "
                        "quedan en el grupo “Sin ETD”.")
            if res["desconocidos"]:
                st.info("Estos estados de la fábrica no se reconocieron y no cambian nada: " + ", ".join(res["desconocidos"]))
            if modo == "r":
                st.warning("Comparando solo por referencia: si una referencia está en varios pedidos, todos reciben "
                           "la misma ETA y cantidad.")
            if not res["coinciden"]:
                st.error("Ningún pendiente coincide. Revisa que las columnas sean las correctas (el pedido de la "
                         "fábrica es Doc.ventas). No se puede aplicar una carga sin coincidencias.")
            if st.button("Aplicar actualización", type="primary", disabled=not res["coinciden"]):
                with st.spinner("Aplicando la actualización…"):
                    doc = L.aplicar_carga(res, " + ".join(nombres_arch), modo, rows)
                refrescar()
                st.session_state.ultima_carga = doc
                st.session_state.up_v += 1
                st.session_state.tabla_v += 1
                st.rerun()


# ================================================================== Lista de empaque
def mostrar_empaque(doc: dict, key: str):
    s = doc.get("resumen") or {k: len(doc.get(k, [])) for k in ("llegan", "yaLlego", "noBo")}
    m = st.columns(3)
    m[0].metric("Del BO que llegan", s.get("llegan", 0))
    m[1].metric("Ya estaban como Llegó", s.get("yaLlego", 0))
    m[2].metric("No son del BO", s.get("noBo", 0))
    st.markdown("**Repuestos del BO que llegan** — coinciden pedido y referencia. Si llega todo lo pedido quedan en "
                "Llegó; si llega menos, en Parcial.")
    st.dataframe(pd.DataFrame([{"Pedido": x["pedido"], "Referencia": x["ref"], "Descripción": x["desc"],
                                "Llega": x["cant"], "Recibido / pedido": f"{x['recibido']} / {x['pedida']}",
                                "Estado actual": x["estadoAntes"],
                                "Queda en": x["nuevo"] + (" (ya registrado)" if x.get("ya") else ""),
                                "Cliente": x.get("cliente")} for x in doc.get("llegan", [])]),
                 hide_index=True, width="stretch")
    st.markdown(f"**Ya estaban como Llegó o Cancelado ({len(doc.get('yaLlego', []))})**")
    st.dataframe(pd.DataFrame([{"Pedido": x["pedido"], "Referencia": x["ref"], "Descripción": x["desc"],
                                "Llega": x["cant"], "Estado": x.get("estado"),
                                "Llegada": L.fmt_d(x.get("llegada"))} for x in doc.get("yaLlego", [])]),
                 hide_index=True, width="stretch")
    with st.expander(f"No son del BO ({len(doc.get('noBo', []))}) — el pedido y la referencia no coinciden con ningún BO"):
        st.dataframe(pd.DataFrame([{"Pedido": x["pedido"], "Referencia": x["ref"], "Descripción": x["desc"],
                                    "Llega": x["cant"], "Caja": x.get("cajas")} for x in doc.get("noBo", [])]),
                     hide_index=True, width="stretch")
    st.download_button("Descargar validación (Excel)", L.excel_empaque(doc),
                       f"Lista de empaque {doc.get('entrega', '')} validacion.xlsx", key=f"dle_{key}")


with tab_e:
    if st.session_state.get("ultimo_empaque"):
        d = st.session_state.ultimo_empaque
        st.success(f"Llegada registrada · lista de empaque {d['entrega']}")
        mostrar_empaque(d, "ult")
        if st.button("Subir otra lista"):
            st.session_state.ultimo_empaque = None
            st.rerun()
    else:
        st.write("Sube la **lista de empaque en PDF** que llega con el despacho. Cada repuesto se busca en el BO por "
                 "**pedido y referencia**; solo cuenta como BO si coinciden los dos. Después decides si registrar la llegada.")
        pdf = st.file_uploader("Lista de empaque (PDF)", type=["pdf"], key=f"pk_{st.session_state.pk_v}")
        pk = None
        if pdf:
            try:
                pk = L.leer_lista_empaque(pdf.getvalue())
            except Exception:
                st.error("No se pudo leer ese PDF. Revisa que sea la lista de empaque original (no una foto escaneada).")
        if pk is not None:
            if not pk["items"]:
                st.error("No encontré repuestos en ese PDF. Revisa que sea la lista de empaque (con columnas Caja, "
                         "Producto, Pedido y Cantidad).")
            else:
                st.markdown(f"### Lista de empaque {pk['entrega']}  \n{L.fmt_d(pk['fecha'])} · {pk['lineas']} líneas · "
                            f"{pk['unidades']} unidades")
                if any(e.get("entrega") == pk["entrega"] for e in _historial()[1]):
                    st.warning(f"Esta lista ({pk['entrega']}) ya se había registrado. Los repuestos que ya la tienen no "
                               "se vuelven a sumar.")
                res = L.clasificar_empaque(rows, pk)
                doc_prev = {**res, "entrega": pk["entrega"],
                            "resumen": {k: len(v) for k, v in res.items()}}
                mostrar_empaque(doc_prev, "prev")
                por = sum(1 for x in res["llegan"] if not x["ya"])
                if st.button(f"Registrar llegada de {por}" if por else "Nada por registrar", type="primary",
                             disabled=not por):
                    doc = L.registrar_empaque(rows, pk, res, pdf.name)
                    refrescar()
                    st.session_state.ultimo_empaque = doc
                    st.session_state.pk_v += 1
                    st.session_state.tabla_v += 1
                    st.rerun()


# ================================================================== Reportes
with tab_r:
    st.markdown("#### Reporte por canal (PDF)")
    st.caption("PDF protegido contra edición, listo para enviar. Ordenado por ETA.")
    cs = L.canales_presentes(rows)
    c1, c2 = st.columns(2)
    canal = c1.selectbox("Canal", ["__all"] + cs, format_func=lambda c: "Todos los canales (una sección por canal)"
                         if c == "__all" else c)
    alcance = c2.selectbox("Qué incluir", ["bo", "vencida", "todos"], format_func={
        "bo": "Solo backorder (Pendiente + Parcial)", "vencida": "Solo ETA vencida (Alerta)",
        "todos": "Todos los estados"}.get)
    partes = [(c, len(L.filas_reporte(rows, c, alcance))) for c in (cs if canal == "__all" else [canal])]
    partes = [p for p in partes if p[1]]
    total = sum(p[1] for p in partes)
    st.info(f"El PDF tendrá **{nf(total)}** repuestos" + (", una sección por canal: " + ", ".join(
        f"{c} ({nf(n)})" for c, n in partes) if canal == "__all" else "") + "." if total else
            "No hay repuestos para ese canal con ese filtro.")
    if st.button("Generar PDF", type="primary", disabled=not total):
        st.session_state.pdf_rep = (L.pdf_canal(rows, canal, alcance, cfg.get("actualizado")),
                                    f"Backorder {'todos los canales' if canal == '__all' else canal} {HOY}.pdf")
    if st.session_state.get("pdf_rep"):
        data, nombre = st.session_state.pdf_rep
        st.download_button(f"Descargar {nombre}", data, nombre, mime="application/pdf")

    st.divider()
    st.markdown("#### Tablero completo (Excel)")
    if st.button("Preparar Excel del tablero"):
        st.session_state.xlsx_tab = L.excel_tablero(rows)
    if st.session_state.get("xlsx_tab"):
        st.download_button("Descargar Excel", st.session_state.xlsx_tab, f"Backorder Yokomotor 173 - {HOY}.xlsx")

    st.divider()
    st.markdown("#### Respaldo completo")
    st.caption("Guarda todo el tablero (repuestos, cargas y listas de empaque) en un archivo. Descárgalo una vez "
               "por semana y guárdalo en tu computador: si algo le pasa a la base de datos, con este archivo se "
               "recupera todo.")
    if st.button("Preparar respaldo"):
        st.session_state.resp = L.exportar_respaldo()
    if st.session_state.get("resp"):
        st.download_button("Descargar respaldo", st.session_state.resp, f"backorder_respaldo_{HOY}.json",
                           mime="application/json")


# ================================================================== Actualizaciones
with tab_h:
    st.markdown("#### Listas de empaque")
    cgs_hist, emps = _historial()
    if not emps:
        st.caption("Todavía no has subido listas de empaque.")
    for e in emps:
        s = e.get("resumen", {})
        with st.expander(f"Entrega {e.get('entrega')} · {L.fmt_d(e.get('fecha'))} — {s.get('llegan', 0)} del BO · "
                         f"{s.get('noBo', 0)} no son del BO · registrada {L.fmt_d(e.get('aplicada'))}"):
            mostrar_empaque(e, "hist_" + e["id"])
    st.markdown("#### Cargas del Excel de fábrica")
    cgs = cgs_hist
    if not cgs:
        st.caption("Todavía no hay actualizaciones.")
    for c in cgs:
        s = c.get("resumen", {})
        with st.expander(f"{L.fmt_d(c.get('fecha'))} · {c.get('archivo')} — {s.get('coinciden', 0)} coinciden · "
                         f"{s.get('faltantes', 0)} no aparecen · {s.get('nuevos', 0)} nuevos"):
            mostrar_carga(c, "hist")
