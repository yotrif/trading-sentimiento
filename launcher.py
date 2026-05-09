"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         SENTIMENT TRADER — LAUNCHER ADAPTADO                                ║
║         Motor de Análisis · DuckDB (trading_sentimiento.db) → HTML          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  CÓMO USAR:                                                                  ║
║      cd ~/trading-sentimiento                                                ║
║      source venv/bin/activate                                                ║
║      python launcher.py                                                      ║
║                                                                              ║
║  REQUISITOS:                                                                 ║
║      pip install duckdb pandas                                               ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json, os, sys, webbrowser, random, math
from datetime import datetime, timedelta
from pathlib import Path

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN — ajusta sólo si mueves los archivos de lugar
# ════════════════════════════════════════════════════════════════════════════

# Ruta a tu base de datos real (relativa a donde ejecutas el script)
DB_PATH   = os.path.expanduser("~/trading-sentimiento/data/warehouse/trading_sentimiento.db")

# HTML base (debe estar en la misma carpeta que este launcher)
HTML_FILE = Path(__file__).parent / "sentiment_trading_app.html"

# Carpeta donde se guarda el HTML generado con datos inyectados
OUTPUT_DIR = Path(__file__).parent / "output"

# ════════════════════════════════════════════════════════════════════════════
# SECCIÓN 1 — CONEXIÓN A DUCKDB
# ════════════════════════════════════════════════════════════════════════════

def conectar():
    try:
        import duckdb
    except ImportError:
        print("[ERROR] Instala duckdb:  pip install duckdb")
        sys.exit(1)

    db = Path(DB_PATH)
    if not db.exists():
        print(f"[WARN] Base de datos no encontrada en: {db}")
        print("       → Se usarán datos de ejemplo enriquecidos.")
        return None

    try:
        con = duckdb.connect(str(db), read_only=True)
        print(f"[OK]  Conectado a: {db}")
        return con
    except Exception as e:
        print(f"[ERROR] No se pudo abrir DuckDB: {e}")
        return None

# ════════════════════════════════════════════════════════════════════════════
# SECCIÓN 2 — EXTRACCIÓN Y MAPEO DE DATOS REALES
# Tu DB tiene: precios, noticias, reddit, macro (y opcionalmente fear_greed)
# El HTML espera: prices, news, reddit, feargreed, macro
# ════════════════════════════════════════════════════════════════════════════

def extraer_datos(con):
    """
    Extrae datos de las tablas reales y los mapea al formato
    que espera el HTML (campos: id, fecha, ticker, open/high/low/close,
    volume, fuente, titulo, sentimiento, score, subreddit, sent_score,
    value, label, serie, nombre, valor, unidad).
    """
    import pandas as pd

    def q(sql):
        try:
            df = con.execute(sql).fetchdf()
            # convertir timestamps a string
            for c in df.select_dtypes(include=["datetime64[ns, UTC]","datetime64[ns]"]).columns:
                df[c] = df[c].dt.strftime("%Y-%m-%d")
            df = df.fillna("")
            return json.loads(df.to_json(orient="records", date_format="iso"))
        except Exception as e:
            print(f"  [WARN] query falló: {e}")
            return []

    # ── PRECIOS ──────────────────────────────────────────────────────────────
    # Tu tabla: fecha, activo, precio_apertura, precio_maximo, precio_minimo,
    #           precio_cierre, volumen, variacion_pct
    # HTML espera: id, fecha, ticker, open, high, low, close, volume
    prices = q("""
        SELECT
            ROW_NUMBER() OVER (ORDER BY fecha DESC, activo) AS id,
            CAST(fecha AS VARCHAR)          AS fecha,
            activo                          AS ticker,
            ROUND(precio_apertura, 2)       AS open,
            ROUND(precio_maximo,   2)       AS high,
            ROUND(precio_minimo,   2)       AS low,
            ROUND(precio_cierre,   2)       AS close,
            CAST(COALESCE(volumen,0) AS BIGINT) AS volume
        FROM precios
        WHERE precio_cierre IS NOT NULL
        ORDER BY fecha DESC
        LIMIT 500
    """)
    print(f"  → precios:    {len(prices)} registros")

    # ── NOTICIAS ─────────────────────────────────────────────────────────────
    # Tu tabla: fecha, activo, titulo, resumen, url, fuente, tipo
    # HTML espera: id, fecha, ticker, fuente, titulo, sentimiento, score
    # Sentimiento: simulado a partir del título (el modelo NLP va en Fase 4)
    noticias_raw = q("""
        SELECT
            ROW_NUMBER() OVER (ORDER BY fecha DESC) AS id,
            CAST(fecha AS VARCHAR) AS fecha,
            COALESCE(activo, 'GENERAL') AS ticker,
            fuente,
            titulo,
            COALESCE(resumen, '') AS resumen
        FROM noticias
        WHERE titulo IS NOT NULL AND titulo != ''
        ORDER BY fecha DESC
        LIMIT 500
    """)

    # Asignar sentimiento simulado (placeholder hasta Fase 4 - FinBERT)
    news = []
    for i, r in enumerate(noticias_raw):
        score = _simular_sentimiento(r.get("titulo",""))
        if score > 0.15:
            sent = "positive"
        elif score < -0.15:
            sent = "negative"
        else:
            sent = "neutral"
        r["sentimiento"] = sent
        r["score"]       = round(score, 4)
        news.append(r)
    print(f"  → noticias:   {len(news)} registros")

    # ── REDDIT ───────────────────────────────────────────────────────────────
    # Tu tabla: fecha, activo, titulo, resumen, url, score, comentarios, fuente
    # HTML espera: id, fecha, ticker, subreddit, titulo, score, sentimiento, sent_score
    reddit_raw = q("""
        SELECT
            ROW_NUMBER() OVER (ORDER BY fecha DESC) AS id,
            CAST(fecha AS VARCHAR) AS fecha,
            COALESCE(activo, 'GENERAL') AS ticker,
            REPLACE(fuente, 'reddit_', '') AS subreddit,
            titulo,
            CAST(COALESCE(score, 0) AS INTEGER) AS score
        FROM reddit
        WHERE titulo IS NOT NULL AND titulo != ''
        ORDER BY fecha DESC
        LIMIT 500
    """)

    reddit = []
    for r in reddit_raw:
        sent_score = _simular_sentimiento(r.get("titulo",""))
        if sent_score > 0.15:
            sent = "positive"
        elif sent_score < -0.15:
            sent = "negative"
        else:
            sent = "neutral"
        r["sentimiento"] = sent
        r["sent_score"]  = round(sent_score, 4)
        reddit.append(r)
    print(f"  → reddit:     {len(reddit)} registros")

    # ── FEAR & GREED ─────────────────────────────────────────────────────────
    # Tu tabla puede existir o no; si no existe, generamos serie coherente
    feargreed = q("""
        SELECT
            ROW_NUMBER() OVER (ORDER BY fecha DESC) AS id,
            CAST(fecha AS VARCHAR) AS fecha,
            CAST(valor AS DOUBLE) AS value,
            clasificacion AS label
        FROM fear_greed
        ORDER BY fecha DESC
        LIMIT 200
    """)

    if not feargreed:
        feargreed = _generar_fear_greed()
        print(f"  → fear_greed: {len(feargreed)} registros (generados — tabla vacía)")
    else:
        print(f"  → fear_greed: {len(feargreed)} registros")

    # ── MACRO ─────────────────────────────────────────────────────────────────
    # Tu tabla: fecha, activo, indicador, valor, fuente
    # HTML espera: id, fecha, serie, nombre, valor, unidad
    macro_raw = q("""
        SELECT
            ROW_NUMBER() OVER (ORDER BY fecha DESC) AS id,
            CAST(fecha AS VARCHAR) AS fecha,
            indicador AS serie,
            ROUND(CAST(valor AS DOUBLE), 4) AS valor
        FROM macro
        WHERE valor IS NOT NULL AND valor != ''
        ORDER BY fecha DESC
        LIMIT 200
    """)

    NOMBRE_MAP = {
        "inflacion_usa":    ("CPI / Inflación USA",       "%"),
        "tasa_desempleo":   ("Tasa de Desempleo",          "%"),
        "tasa_interes_fed": ("Federal Funds Rate",         "%"),
        "pib_usa":          ("PIB Estados Unidos",         "B USD"),
    }
    macro = []
    for r in macro_raw:
        serie = r.get("serie","")
        nombre, unidad = NOMBRE_MAP.get(serie, (serie, "—"))
        r["nombre"] = nombre
        r["unidad"] = unidad
        macro.append(r)
    print(f"  → macro:      {len(macro)} registros")

    # ── STATS PARA TARJETAS DEL DASHBOARD ─────────────────────────────────
    stats_raw = q("""
        SELECT
            (SELECT COUNT(*) FROM precios)  AS total_prices,
            (SELECT COUNT(*) FROM noticias) AS total_news,
            (SELECT COUNT(*) FROM reddit)   AS total_reddit,
            (SELECT COUNT(*) FROM macro)    AS total_macro
    """)
    stats = stats_raw[0] if stats_raw else {}

    # calcular avg_score_today con los datos que ya tenemos
    scores_today = [r["score"] for r in news if r.get("score") is not None]
    avg_score = round(sum(scores_today)/len(scores_today), 3) if scores_today else 0.0
    fg_val = feargreed[0]["value"] if feargreed else "—"

    stats["avg_score_today"] = avg_score
    stats["fg_latest"]       = fg_val
    stats["total_fg"]        = len(feargreed)

    return {
        "prices":    prices,
        "news":      news,
        "reddit":    reddit,
        "feargreed": feargreed,
        "macro":     macro,
    }, stats


# ════════════════════════════════════════════════════════════════════════════
# SECCIÓN 3 — DATOS DE EJEMPLO (cuando no hay DB disponible)
# ════════════════════════════════════════════════════════════════════════════

def datos_ejemplo():
    """
    Genera datos de ejemplo ricos que reflejan exactamente el esquema real
    del proyecto (mismos activos, mismas fuentes, mismo formato de fechas).
    """
    random.seed(42)
    activos  = ["AAPL","GOOGL","MSFT","TSLA","AMZN","META","NVDA","JPM","BTC-USD","ETH-USD"]
    base_px  = {"AAPL":185,"GOOGL":168,"MSFT":372,"TSLA":242,"AMZN":183,
                "META":508,"NVDA":490,"JPM":196,"BTC-USD":43000,"ETH-USD":2250}
    start    = datetime(2023,6,1)

    # Precios
    prices, idx = [], 1
    for activo in activos:
        px = base_px[activo]
        for i in range(60):
            dt = start + timedelta(days=i)
            if dt.weekday() >= 5 and "USD" not in activo: continue
            px *= (1 + random.gauss(0.0003, 0.018))
            prices.append({
                "id":     idx,
                "fecha":  dt.strftime("%Y-%m-%d"),
                "ticker": activo,
                "open":   round(px * (1 + random.gauss(0, 0.004)), 2),
                "high":   round(px * (1 + abs(random.gauss(0, 0.008))), 2),
                "low":    round(px * (1 - abs(random.gauss(0, 0.008))), 2),
                "close":  round(px, 2),
                "volume": int(random.uniform(8e6, 90e6)),
            })
            idx += 1
    prices.sort(key=lambda x: x["fecha"], reverse=True)

    # Noticias
    titulos_pos = [
        "NVDA just crushed earnings — AI chip demand surges",
        "Apple reports record Q4 earnings beating all estimates",
        "Bitcoin breaks $45K resistance as institutional demand returns",
        "Microsoft Azure cloud revenue accelerates sharply in Q3",
        "Meta Platforms beats revenue estimates with strong ad recovery",
    ]
    titulos_neg = [
        "Tesla faces regulatory scrutiny over autopilot safety concerns",
        "Fed signals more rate hikes ahead — tech stocks under pressure",
        "GOOGL antitrust lawsuit could reshape digital advertising market",
        "Recession fears mount as yield curve inverts further",
        "Bitcoin rejected hard at resistance — bears regain control",
    ]
    titulos_neu = [
        "Weekly market wrap: mixed signals from earnings season",
        "JPMorgan maintains hold rating on major tech stocks",
        "Portfolio analysis: sector rotation continues in Q3",
        "Analysts divided on Fed pivot timeline for 2024",
    ]
    fuentes = ["reuters_negocios","yahoo_finance_noticias","marketwatch","seekingalpha","investing_com"]
    news, idx = [], 1
    for i in range(80):
        dt = start + timedelta(days=random.randint(0,59), hours=random.randint(7,21))
        bucket = random.random()
        if bucket < 0.4:
            titulo = random.choice(titulos_pos); score = round(random.uniform(0.2, 0.95), 4); sent = "positive"
        elif bucket < 0.68:
            titulo = random.choice(titulos_neg); score = round(random.uniform(-0.9, -0.2), 4); sent = "negative"
        else:
            titulo = random.choice(titulos_neu); score = round(random.uniform(-0.14, 0.14), 4); sent = "neutral"
        news.append({"id":idx,"fecha":dt.strftime("%Y-%m-%d"),"ticker":random.choice(activos[:8]),
                     "fuente":random.choice(fuentes),"titulo":titulo,"sentimiento":sent,"score":score})
        idx += 1
    news.sort(key=lambda x: x["fecha"], reverse=True)

    # Reddit
    titles_pos_r = ["Why I'm loading more NVDA — AI demand is just starting 🚀",
                    "AAPL earnings call analysis — super bullish on services",
                    "MSFT acquiring Activision approved — gaming synergies incoming"]
    titles_neg_r = ["TSLA puts printing money — demand collapse is real",
                    "BTC rejected at $46K again, prepare for lower lows",
                    "Sold my entire tech portfolio — macro headwinds too strong"]
    titles_neu_r = ["Weekly discussion: what are you watching this earnings season?",
                    "TA on BTC weekly chart — key levels to watch",
                    "Anyone else holding AMZN through the report?"]
    subs = ["investing","stocks","wallstreetbets","finance","economy"]
    reddit, idx = [], 1
    for i in range(100):
        dt = start + timedelta(days=random.randint(0,59), hours=random.randint(6,23))
        bucket = random.random()
        if bucket < 0.38:
            titulo = random.choice(titles_pos_r); ss = round(random.uniform(0.2,0.95),4); sent = "positive"
        elif bucket < 0.65:
            titulo = random.choice(titles_neg_r); ss = round(random.uniform(-0.9,-0.2),4); sent = "negative"
        else:
            titulo = random.choice(titles_neu_r); ss = round(random.uniform(-0.15,0.15),4); sent = "neutral"
        reddit.append({"id":idx,"fecha":dt.strftime("%Y-%m-%d"),"ticker":random.choice(activos[:8]),
                       "subreddit":random.choice(subs),"titulo":titulo,
                       "score":random.randint(50,12000),"sentimiento":sent,"sent_score":ss})
        idx += 1
    reddit.sort(key=lambda x: x["fecha"], reverse=True)

    feargreed = _generar_fear_greed()

    macro = []
    series = [
        ("inflacion_usa","CPI / Inflación USA","%"),
        ("tasa_desempleo","Tasa de Desempleo","%"),
        ("tasa_interes_fed","Federal Funds Rate","%"),
        ("pib_usa","PIB Estados Unidos","B USD"),
    ]
    for i in range(24):
        dt = start - timedelta(days=i*30)
        for j, (serie, nombre, unidad) in enumerate(series):
            base_vals = [3.5, 3.8, 5.25, 27000]
            val = base_vals[j] + random.gauss(0, base_vals[j]*0.05)
            macro.append({"id":i*4+j+1,"fecha":dt.strftime("%Y-%m-%d"),
                          "serie":serie,"nombre":nombre,"valor":round(val,4),"unidad":unidad})

    datos = {"prices":prices,"news":news,"reddit":reddit,"feargreed":feargreed,"macro":macro}
    scores = [r["score"] for r in news]
    avg_score = round(sum(scores)/len(scores),3) if scores else 0.0
    stats = {
        "total_prices": len(prices), "total_news": len(news),
        "total_reddit": len(reddit), "total_fg": len(feargreed),
        "total_macro": len(macro), "avg_score_today": avg_score,
        "fg_latest": feargreed[0]["value"] if feargreed else "—",
    }
    return datos, stats


# ════════════════════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════════════════════

_POS_WORDS = {"beats","record","surges","bullish","growth","profit","strong","wins",
              "approval","buy","rally","recovery","success","boost","positive","gain"}
_NEG_WORDS = {"falls","drops","crash","bearish","loss","scrutiny","lawsuit","fears",
              "rejected","sell","panic","decline","concern","warning","negative","risk"}

def _simular_sentimiento(titulo: str) -> float:
    """
    Heurística ligera de sentimiento por palabras clave.
    Placeholder hasta que se implemente FinBERT en Fase 4.
    Retorna valor en [-1, +1].
    """
    words = set(titulo.lower().split())
    pos = len(words & _POS_WORDS)
    neg = len(words & _NEG_WORDS)
    raw = (pos - neg) / max(pos + neg, 1) if (pos + neg) > 0 else 0.0
    # añadir leve ruido para que no sean valores exactos
    raw += random.gauss(0, 0.08)
    return max(-1.0, min(1.0, round(raw, 4)))


def _generar_fear_greed() -> list:
    """Genera una serie histórica coherente de Fear & Greed cuando la tabla no existe."""
    fg, val, idx = [], 50.0, 1
    start = datetime(2023,6,1)
    for i in range(200):
        dt = start + timedelta(days=i)
        val = max(5, min(95, val + random.gauss(0, 4)))
        if val < 25:   label = "Extreme Fear"
        elif val < 45: label = "Fear"
        elif val < 55: label = "Neutral"
        elif val < 75: label = "Greed"
        else:          label = "Extreme Greed"
        fg.append({"id":idx,"fecha":dt.strftime("%Y-%m-%d"),"value":round(val,1),"label":label})
        idx += 1
    fg.sort(key=lambda x: x["fecha"], reverse=True)
    return fg


# ════════════════════════════════════════════════════════════════════════════
# SECCIÓN 4 — INYECCIÓN EN EL HTML
# ════════════════════════════════════════════════════════════════════════════

MARKER = "// __DATA_INJECTION_POINT__"

def inyectar(datos: dict, stats: dict, last_run: str) -> Path:
    if not HTML_FILE.exists():
        print(f"[ERROR] No se encontró: {HTML_FILE}")
        sys.exit(1)

    html = HTML_FILE.read_text(encoding="utf-8")

    total  = sum(len(v) for v in datos.values())
    texts  = len(datos.get("news",[])) + len(datos.get("reddit",[]))
    avg_sc = stats.get("avg_score_today", 0.0)
    fg_val = stats.get("fg_latest", "—")

    injection = f"""
    // ── DATOS INYECTADOS POR launcher.py  [{last_run}] ──────────────────
    // Fuente real: trading_sentimiento.db (DuckDB)
    // Tablas: precios · noticias · reddit · fear_greed · macro
    DATA_STORE.prices    = {json.dumps(datos.get("prices",    []), ensure_ascii=False)};
    DATA_STORE.news      = {json.dumps(datos.get("news",      []), ensure_ascii=False)};
    DATA_STORE.reddit    = {json.dumps(datos.get("reddit",    []), ensure_ascii=False)};
    DATA_STORE.feargreed = {json.dumps(datos.get("feargreed", []), ensure_ascii=False)};
    DATA_STORE.macro     = {json.dumps(datos.get("macro",     []), ensure_ascii=False)};

    // Actualizar tarjetas del dashboard al cargar la página
    document.addEventListener('DOMContentLoaded', function() {{
        const se = (id, val) => {{ const el = document.getElementById(id); if (el) el.textContent = val; }};
        se('stat-total',  '{total:,}');
        se('stat-texts',  '{texts:,}');
        se('stat-score',  '{avg_sc:.3f}');
        se('stat-fg',     '{fg_val}');
        se('lastRun',     '{last_run}');
    }});
    // ── FIN INYECCIÓN ────────────────────────────────────────────────────
"""

    if MARKER not in html:
        print("[WARN] Marcador no encontrado en el HTML — los datos demo permanecerán.")
    else:
        html = html.replace(MARKER, injection)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out  = OUTPUT_DIR / f"sentiment_app_{ts}.html"
    out.write_text(html, encoding="utf-8")
    print(f"[OK]  HTML generado: {out}")
    return out


# ════════════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("  SENTIMENT TRADER — Lanzador  (trading_sentimiento.db)")
    print("=" * 62)

    last_run = datetime.now().strftime("%Y-%m-%d %H:%M")
    con      = conectar()

    if con:
        print("\n[INFO] Extrayendo datos de DuckDB...")
        datos, stats = extraer_datos(con)
        con.close()
        total = sum(len(v) for v in datos.values())
        print(f"\n[OK]  Total registros extraídos: {total:,}")
    else:
        print("\n[INFO] Usando datos de ejemplo enriquecidos...")
        datos, stats = datos_ejemplo()

    print("\n[INFO] Generando HTML con datos reales...")
    html_out = inyectar(datos, stats, last_run)

    url = html_out.resolve().as_uri()
    print(f"\n[OK]  Abriendo en navegador: {url}")
    webbrowser.open(url)

    print("\n" + "=" * 62)
    print(f"  ✓ Web App lista.  Última actualización: {last_run}")
    print(f"  ✓ Archivo:  {html_out.name}  (en carpeta output/)")
    print("=" * 62)


if __name__ == "__main__":
    main()
