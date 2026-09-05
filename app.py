import streamlit as st
import pandas as pd
from google import genai
import os
from datetime import date
from streamlit_gsheets import GSheetsConnection

COLUMNS = ["Date", "Place Name", "Cuisine/Activity", "Rating", "Notes"]
WORKSHEET = "Trips"  # name of the tab inside your Google Sheet

st.set_page_config(page_title="Family Trip Planner", page_icon="🚗", layout="centered")
st.title("🚗 Family Trip & Dinner Planner")

# --- Google Sheets connection (shared store for both of us) ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_data():
    try:
        df = conn.read(worksheet=WORKSHEET, ttl=0)
        df = df.dropna(how="all")  # drop blank trailing rows Sheets sometimes returns
        for col in COLUMNS:
            if col not in df.columns:
                df[col] = None
        return df[COLUMNS]
    except Exception:
        # Empty/brand-new sheet, or the worksheet doesn't exist yet
        return pd.DataFrame(columns=COLUMNS)

def save_data(df):
    conn.update(worksheet=WORKSHEET, data=df)

# --- Pull Gemini API Key Securely from Streamlit Secrets ---
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    api_key = None

with st.sidebar:
    st.header("⚙️ Status")
    if api_key:
        st.success("Gemini API Key loaded securely! ✨")
    else:
        st.error("Gemini API Key not found in Streamlit Secrets.")

df = load_data()
tab1, tab2, tab3 = st.tabs(["📝 Log a Trip", "📅 Past Trips", "✨ AI Suggestions"])

with tab1:
    st.subheader("Add a New Trip or Dinner")
    with st.form("add_trip_form"):
        trip_date = st.date_input("Date", date.today())
        place_name = st.text_input("Place Name")
        cuisine = st.text_input("Cuisine or Activity")
        rating = st.slider("Rating", 1, 5, 3)
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save Entry")

        if submitted:
            if place_name and cuisine:
                new_entry = pd.DataFrame([{
                    "Date": str(trip_date),
                    "Place Name": place_name,
                    "Cuisine/Activity": cuisine,
                    "Rating": rating,
                    "Notes": notes
                }])
                updated_df = pd.concat([df, new_entry], ignore_index=True)
                save_data(updated_df)
                st.success(f"Successfully added '{place_name}'!")
                st.rerun()
            else:
                st.error("Please fill out at least the Place Name and Cuisine/Activity.")

with tab2:
    st.subheader("Our Travel & Dining History")
    if not df.empty:
        st.dataframe(df.sort_values(by="Date", ascending=False), use_container_width=True)
    else:
        st.info("No trips logged yet.")

with tab3:
    st.subheader("Surprise Us!")
    location = st.text_input("Where are we looking?", value="Cambridge, UK")

    if st.button("Get AI Suggestions ✨"):
        if not api_key:
            st.error("Gemini API Key not found in Streamlit Secrets.")
        elif df.empty:
            st.warning("Log at least one past trip first.")
        elif not location:
            st.warning("Please enter your location.")
        else:
            try:
                # Initialize the modern Google GenAI client
                client = genai.Client(api_key=api_key)

                # Split past trips into what we loved vs. what didn't land, based on rating
                trips_df = df.copy()
                trips_df["Rating"] = pd.to_numeric(trips_df["Rating"], errors="coerce")

                loved = trips_df[trips_df["Rating"] >= 4]
                mixed = trips_df[trips_df["Rating"] == 3]
                disliked = trips_df[trips_df["Rating"] <= 2]

                def format_trips(sub_df):
                    if sub_df.empty:
                        return "None yet."
                    lines = []
                    for _, row in sub_df.iterrows():
                        note = row.get("Notes")
                        note_str = f" — {note}" if pd.notna(note) and str(note).strip() else ""
                        lines.append(f"- {row['Place Name']} ({row['Cuisine/Activity']}, rated {row['Rating']}/5){note_str}")
                    return "\n".join(lines)

                prompt = f"""
                You know our family well: me, my wife, and our 4-year-old daughter. We're looking for our next family-friendly weekend trip or dinner spot near {location}.

                Places and activities we've LOVED before (high ratings):
                {format_trips(loved)}

                Places that were just OK (middle ratings):
                {format_trips(mixed)}

                Places that DIDN'T work for us (low ratings) — avoid similar picks:
                {format_trips(disliked)}

                Based on this feedback, suggest 3 NEW places or activities near {location} that we haven't already tried. For each one, write a short, warm, personal note — like a friend who knows our family — explaining specifically why it fits what we've enjoyed before and how it avoids what didn't work for us. DO NOT suggest overlapping cuisines/places we've already been to.
                """
                with st.spinner("Finding fresh recommendations..."):
                    response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=prompt,
                    )
                    st.markdown(response.text)
            except Exception as e:
                st.error(f"An API error occurred: {e}")