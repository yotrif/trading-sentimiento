import os
import time
import feedparser
import requests
import pandas as pd
import yfinance as yf
import duckdb
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Carga las variables del archivo .env
load_dotenv()

# Configuracion global
ACTIVOS = os.getenv("ACTIVOS", "AAPL,GOOGL,MSFY,TSLA").split (",")
FECHA_INICIO = os.getenv("FECHA_INICIO", "2024-01-01")
FECHA_FIN = os.getenv("FECHA_FIN", "2024-12-31")
DB_NOMBRE = os.getenv("DB_NOMBRE", "trading_sentimiento.db")
DB_PATH = f"data/warehouse/{DB_NOMBRE}"

print(f"Configuracion cargada: {len(ACTIVOS)} activos | {FECHA_INICIO}→{FECHA_FIN}")

# Fuente 1 (Yahoo Finance)

def recolectar_precios():
    """
    Descarga precios históricos de cierre, volumen y variación diaria
    para cada activo definido en .env
    Retorna un DataFrame con todos los activos combinados
    """
    print("\n Recolectando precios históricos...")
    registros = []

    for activo in ACTIVOS:
        try:
            ticker = yf.Ticker(activo)
            df = ticker.history(start=FECHA_INICIO, end=FECHA_FIN)

            if df.empty:
                print(f"   Sin datos para {activo}")
                continue

            df = df.reset_index()
            df["activo"] = activo
            df["fuente"] = "yahoo_finance"
            df["tipo"] = "precio"
            df["fecha_recoleccion"] = datetime.now().isoformat()

            # Calcular variación porcentual diaria
            df["variacion_pct"] = df["Close"].pct_change() * 100

            # Seleccionar 11 columnas
            df = df[["Date", "activo", "Open", "High", "Low", "Close",
                     "Volume", "variacion_pct", "fuente", "tipo",
                     "fecha_recoleccion"]]

            df.columns = ["fecha", "activo", "precio_apertura", "precio_maximo",
                          "precio_minimo", "precio_cierre", "volumen",
                          "variacion_pct", "fuente", "tipo", "fecha_recoleccion"]

            registros.append(df)
            print(f"  {activo}: {len(df)} registros")
            time.sleep(0.5)

        except Exception as e:
            print(f"  Error con {activo}: {e}")

    
    if registros:
        resultado = pd.concat(registros, ignore_index=True)
        print(f"\n  Total precios: {len(resultado)} registros")
        return resultado

    return pd.DataFrame()
        
#Fuente 2 (Noticias Financieras)
FEEDS_NOTICIAS = {
    "reuters_negocios":
        "https://feeds.reuters.com/reuters/businessNews",
    "yahoo_finance_noticias":
        "https://finance.yahoo.com/news/rssindex",
    "investing_com":
        "https://www.investing.com/rss/news.rss",
    "marketwatch":
        "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    "seekingalpha":
        "https://seekingalpha.com/feed.xml",
}

def recolectar_noticias():
    """
    Lee feeds RSS de medios financieros reconocidos.
    Extrae título, resumen, fecha y fuente de cada artículo.
    """
    print("\n Recolectando noticias financieras...")
    registros = []

    for nombre_fuente, url in FEEDS_NOTICIAS.items():
        try:
            feed = feedparser.parse(url)

            if not feed.entries:
                print(f"   Sin entradas en {nombre_fuente}")
                continue

            for entry in feed.entries:
                # Extraer fecha de publicación de forma segura
                fecha_pub = entry.get("published", "")
                try:
                    fecha_pub = datetime(*entry.published_parsed[:6]).isoformat()
                except Exception:
                    fecha_pub = datetime.now().isoformat()

                registro = {
                    "fecha": fecha_pub,
                    "activo": "GENERAL",
                    "titulo": entry.get("title", ""),
                    "resumen": entry.get("summary", "")[:500],
                    "url": entry.get("link", ""),
                    "fuente": nombre_fuente,
                    "tipo": "noticia",
                    "fecha_recoleccion": datetime.now().isoformat(),
                }
                registros.append(registro)

            print(f"  {nombre_fuente}: {len(feed.entries)} noticias")
            time.sleep(1)  # Pausa entre fuentes

        except Exception as e:
            print(f"   Error con {nombre_fuente}: {e}")

    resultado = pd.DataFrame(registros)
    print(f"\n   Total noticias: {len(resultado)} registros")
    return resultado

#FUENTE 3:(Reddit)

SUBREDDITS = ["investing", "stocks", "wallstreetbets", "finance", "economy"]

def recolectar_reddit():
    """
    Usa la API JSON pública de Reddit (no requiere cuenta ni API key).
    Extrae los posts más relevantes de subreddits financieros.
    """
    print("\n Recolectando posts de Reddit...")
    registros = []
    headers = {"User-Agent": "TradingBot/1.0 (proyecto educativo)"}

    for subreddit in SUBREDDITS:
        for categoria in ["hot", "top"]:
            try:
                url = f"https://www.reddit.com/r/{subreddit}/{categoria}.json?limit=50"
                response = requests.get(url, headers=headers, timeout=10)

                if response.status_code != 200:
                    print(f"    Error {response.status_code} en r/{subreddit}")
                    continue

                posts = response.json()["data"]["children"]

                for post in posts:
                    data = post["data"]
                    registro = {
                        "fecha": datetime.fromtimestamp(
                            data.get("created_utc", 0)
                        ).isoformat(),
                        "activo": "GENERAL",
                        "titulo": data.get("title", ""),
                        "resumen": data.get("selftext", "")[:500],
                        "url": f"https://reddit.com{data.get('permalink', '')}",
                        "score": data.get("score", 0),
                        "comentarios": data.get("num_comments", 0),
                        "fuente": f"reddit_{subreddit}",
                        "tipo": "foro",
                        "fecha_recoleccion": datetime.now().isoformat(),
                    }
                    registros.append(registro)

                print(f"   r/{subreddit}/{categoria}: {len(posts)} posts")
                time.sleep(2)  # Reddit pide cortesía entre requests

            except Exception as e:
                print(f"   Error en r/{subreddit}: {e}")

    resultado = pd.DataFrame(registros)
    print(f"\n   Total Reddit: {len(resultado)} registros")
    return resultado

#FUENTE 4: Fear & Greed Index (CNN) 

def recolectar_fear_greed():
    """
    El Fear & Greed Index mide el sentimiento general del mercado
    en una escala del 0 (miedo extremo) al 100 (codicia extrema).
    """
    print("\n Recolectando Fear & Greed Index...")
    registros = []

    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            historial = data.get("fear_and_greed_historical", {}).get("data", [])

            for punto in historial:
                registros.append({
                    "fecha": datetime.fromtimestamp(
                        punto["x"] / 1000
                    ).isoformat(),
                    "activo": "MERCADO_GENERAL",
                    "valor": round(punto["y"], 2),
                    "clasificacion": punto.get("rating", ""),
                    "fuente": "cnn_fear_greed",
                    "tipo": "sentimiento_mercado",
                    "fecha_recoleccion": datetime.now().isoformat(),
                })

            print(f"  Fear & Greed: {len(registros)} registros históricos")

    except Exception as e:
        print(f"  Error Fear & Greed: {e}")

    return pd.DataFrame(registros)


# ─── FUENTE 5: Datos macroeconómicos (FRED - Reserva Federal) ────────────────

INDICADORES_MACRO = {
    "inflacion_usa": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
    "tasa_desempleo": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=UNRATE",
    "tasa_interes_fed": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS",
    "pib_usa": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDP",
}

def recolectar_datos_macro():
    """
    La Reserva Federal de EE.UU. publica datos económicos gratuitamente.
    Estos indicadores macro afectan directamente los mercados financieros.
    """
    print("\n Recolectando datos macroeconómicos (FRED)...")
    registros = []

    for nombre, url in INDICADORES_MACRO.items():
        try:
            df = pd.read_csv(url)
            df.columns = ["fecha", "valor"]
            df["activo"] = "MACRO_USA"
            df["indicador"] = nombre
            df["fuente"] = "fred_reserva_federal"
            df["tipo"] = "macro"
            df["fecha_recoleccion"] = datetime.now().isoformat()
            df = df[df["valor"] != "."]  # Eliminar valores vacíos
            registros.append(df)
            print(f"   {nombre}: {len(df)} registros")
            time.sleep(0.5)

        except Exception as e:
            print(f"   Error en {nombre}: {e}")

    if registros:
        return pd.concat(registros, ignore_index=True)
    return pd.DataFrame()

#BASE DE DATOS: Guardar en DuckDB

def guardar_en_warehouse(df_precios, df_noticias, df_reddit,
                          df_fear_greed, df_macro):
    """
    DuckDB es una base de datos analítica que vive en un solo archivo.
    Es perfecta para proyectos locales: rápida, sin servidor, compatible con SQL.
    """
    print("\n Guardando en Data Warehouse (DuckDB)...")

    conn = duckdb.connect(DB_PATH)

    tablas = {
        "precios": df_precios,
        "noticias": df_noticias,
        "reddit": df_reddit,
        "fear_greed": df_fear_greed,
        "macro": df_macro,
    }

    total = 0
    for nombre, df in tablas.items():
        if df is not None and not df.empty:
            conn.execute(f"DROP TABLE IF EXISTS {nombre}")
            conn.execute(
                f"CREATE TABLE {nombre} AS SELECT * FROM df"
            )
            count = conn.execute(
                f"SELECT COUNT(*) FROM {nombre}"
            ).fetchone()[0]
            total += count
            print(f"   Tabla '{nombre}': {count} registros")
        else:
            print(f"    Tabla '{nombre}': sin datos")

    print(f"\n  TOTAL EN WAREHOUSE: {total} registros")
    conn.close()
    return total


# ─── EJECUCIÓN PRINCIPAL ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  MOTOR DE SENTIMIENTO Y TRADING")
    print("  Fase 2: Recolección de datos")
    print("=" * 60)

    inicio = datetime.now()

    df_precios     = recolectar_precios()
    df_noticias    = recolectar_noticias()
    df_reddit      = recolectar_reddit()
    df_fear_greed  = recolectar_fear_greed()
    df_macro       = recolectar_datos_macro()

    total = guardar_en_warehouse(
        df_precios, df_noticias, df_reddit, df_fear_greed, df_macro
    )

    duracion = (datetime.now() - inicio).seconds
    print(f"\n  Completado en {duracion} segundos")
    print(f" Base de datos: {DB_PATH}")

    if total >= 1000:
        print(f" ¡Objetivo cumplido! {total} registros en el warehouse")
    else:
        print(f" Solo {total} registros. Revisa las fuentes con errores.")