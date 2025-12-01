# streamlit_app.py  (à copier-coller tel quel)
import streamlit as st
import pandas as pd
import openmeteo_requests
import requests_cache
from retry_requests import retry
from datetime import date
import plotly.express as px

# ------------------- CONFIG API -------------------
cache_session = requests_cache.CachedSession('.cache', expire_after=-1)
retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
openmeteo = openmeteo_requests.Client(session=retry_session)

# ------------------- UI -------------------
st.set_page_config(page_title="Snowfall History", layout="wide")
st.title("Neige historique – Comparaison & Portefeuille")

st.sidebar.header("Paramètres")
uploaded_file = st.sidebar.file_uploader("Fichier points (lat, lon # nom)", type=["txt"])

start_date = st.sidebar.date_input("Date début", value=date(2020, 1, 1))
end_date = st.sidebar.date_input("Date fin", value=date(2025, 11, 30))

group_by = st.sidebar.selectbox("Regroupement", ["Heure", "Semaine", "Mois"])

# NOUVELLE OPTION : vue individuelle ou portefeuille moyen
view_mode = st.sidebar.radio(
    "Mode d'affichage",
    ["Stations individuelles", "Moyenne du portefeuille"]
)

if uploaded_file is not None:
    # --- Lecture du fichier ---
    lines = uploaded_file.read().decode("utf-8").splitlines()
    points = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        coord_part = line.split("#")[0].strip()
        comment = line.split("#", 1)[1].strip() if "#" in line else coord_part
        if "," in coord_part:
            try:
                lat, lon = map(float, [x.strip() for x in coord_part.split(",", 1)])
                points.append({"lat": lat, "lon": lon, "name": comment})
            except:
                st.warning(f"Ligne ignorée : {line}")

    if not points:
        st.error("Aucun point valide.")
        st.stop()

    st.success(f"{len(points)} station(s) chargée(s)")

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # --- Récupération données ---
    progress_bar = st.progress(0)
    status_text = st.empty()
    all_data = []

    for i, p in enumerate(points):
        status_text.text(f"{i+1}/{len(points)} : {p['name']}")
        params = {
            "latitude": p["lat"],
            "longitude": p["lon"],
            "start_date": start_str,
            "end_date": end_str,
            "hourly": ["snowfall", "snow_depth"],
            "timezone": "auto"
        }
        try:
            resp = openmeteo.weather_api("https://archive-api.open-meteo.com/v1/archive", params)[0]
            hourly = resp.Hourly()

            dates = pd.date_range(
                start=pd.to_datetime(hourly.Time(), unit="s", utc=True),
                end=pd.to_datetime(hourly.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=hourly.Interval()),
                inclusive="left"
            )

            df = pd.DataFrame({
                "date": dates,
                "snowfall_cm": hourly.Variables(0).ValuesAsNumpy(),
                "snow_depth_cm": hourly.Variables(1).ValuesAsNumpy(),
                "location": p["name"]
            })
            all_data.append(df)
        except Exception as e:
            st.error(f"Erreur {p['name']} : {e}")

        progress_bar.progress((i + 1) / len(points))

    progress_bar.empty()
    status_text.empty()

    if not all_data:
        st.stop()

    full_df = pd.concat(all_data, ignore_index=True)
    full_df["date"] = pd.to_datetime(full_df["date"]).dt.tz_localize(None)

    # --- Regroupement temporel ---
    if group_by == "Semaine":
        full_df["period"] = full_df["date"].dt.to_period("W").apply(lambda r: r.start_time)
    elif group_by == "Mois":
        full_df["period"] = full_df["date"].dt.to_period("M").apply(lambda r: r.start_time)
    else:
        full_df["period"] = full_df["date"]

    # --- Agrégation ---
    if view_mode == "Moyenne du portefeuille":
        # On moyenne sur toutes les stations à chaque période
        agg_df = (full_df.groupby("period")
                 .agg(total_snowfall_cm=("snowfall_cm", "sum"),      # somme = chute totale
                      avg_snow_depth_cm=("snow_depth_cm", "mean"),   # moyenne de la hauteur
                      max_snow_depth_cm=("snow_depth_cm", "max"))
                 .reset_index())
        agg_df["location"] = "Portefeuille (moyenne)"

        # Graphiques
        st.header("Moyenne du portefeuille")
        fig1 = px.bar(agg_df, x="period", y="total_snowfall_cm",
                      title="Chute de neige totale – Portefeuille")
        fig1.update_layout(xaxis_title="Période", yaxis_title="Neige tombée (cm)")
        st.plotly_chart(fig1, use_container_width=True)

        fig2 = px.line(agg_df, x="period", y="avg_snow_depth_cm", markers=True,
                       title="Hauteur moyenne de neige au sol – Portefeuille")
        st.plotly_chart(fig2, use_container_width=True)

        # Tableau + download
        st.dataframe(agg_df[["period", "total_snowfall_cm", "avg_snow_depth_cm", "max_snow_depth_cm"]])
        csv = agg_df.to_csv(index=False).encode()
        st.download_button("Télécharger portefeuille (CSV)", csv, "portefeuille_neige.csv", "text/csv")

    else:
        # Mode individuel (comme avant)
        agg_df = (full_df.groupby(["location", "period"])
                 .agg(total_snowfall_cm=("snowfall_cm", "sum"),
                      max_snow_depth_cm=("snow_depth_cm", "max"),
                      mean_snow_depth_cm=("snow_depth_cm", "mean"))
                 .reset_index())

        st.header("Stations individuelles")
        st.dataframe(agg_df.sort_values(["period", "total_snowfall_cm"], ascending=False),
                     use_container_width=True)

        fig1 = px.bar(agg_df, x="period", y="total_snowfall_cm", color="location",
                      title="Neige tombée par station", barmode="group")
        st.plotly_chart(fig1, use_container_width=True)

        fig2 = px.line(agg_df, x="period", y="max_snow_depth_cm", color="location", markers=True,
                       title="Hauteur max de neige par station")
        st.plotly_chart(fig2, use_container_width=True)

        csv = agg_df.to_csv(index=False).encode()
        st.download_button("Télécharger toutes les stations (CSV)", csv, "stations_neige.csv", "text/csv")

else:
    st.info("Charger le fichier de coordonnées")
    st.code("""45.833, 6.867 # Courchevel
45.923, 6.063 # Chamonix
46.375, 6.458 # Avoriaz
45.920, -74.150 # Mont Tremblant""", language="text")