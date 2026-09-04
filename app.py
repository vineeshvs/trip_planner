import streamlit as st
import pandas as pd
import google.generativeai as genai
import os
from datetime import date

# File for logging our trip history
DATA_FILE = "family_trips.csv"

def load_data():
    if os.path.exists(DATA_FILE):
        return pd.read_csv(DATA_FILE)
    else:
        return pd.DataFrame(columns=["Date", "Place Name", "Cuisine/Activity", "Rating", "Notes"])

def save_data(df):
    df.to_csv(DATA_FILE, index=False)

st.set_page_config(page_title="Family Trip Planner", page_icon="🚗", layout="centered")
st.title("🚗 Family Trip & Dinner Planner")

# --- Pull API Key Securely from Streamlit Secrets ---
try:
    api_key = st.secrets["GEMINI_API_KEY"]
except Exception:
    api_key = None

with st.sidebar:
    st.header("⚙️ Status")
    if api_key:
        st.success("API Key loaded securely from Secrets! ✨")
    else:
        st.error("API Key not found in Streamlit Secrets.")

df = load_data()
tab1, tab2, tab3 = st.tabs(["📝 Log a Trip", "📅 Past Trips", "✨ AI Suggestions"])

# Tab 1: Input Form
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
                df = pd.concat([df, new_entry], ignore_index=True)
                save_data(df)
                st.success(f"Successfully added '{place_name}'!")
                st.rerun()
            else:
                st.error("Please fill out at least the Place Name and Cuisine/Activity.")

# Tab 2: History Log
with tab2:
    st.subheader("Our Travel & Dining History")
    if not df.empty:
        st.dataframe(df.sort_values(by="Date", ascending=False), use_container_width=True)
    else:
        st.info("No trips logged yet.")

# Tab 3: Recommendation Engine
with tab3:
    st.subheader("Surprise Us!")
    location = st.text_input("Where are we looking?", value="Cambridge, UK")
    
    if st.button("Get AI Suggestions ✨"):
        if not api_key:
            st.error("Please enter your API Key.")
        elif df.empty:
            st.warning("Log at least one past trip first.")
        elif not location:
            st.warning("Please enter your location.")
        else:
            try:
                genai.configure(api_key=api_key)
                recent_trips = df.tail(10).to_dict(orient='records')
                prompt = f"""
                My wife, our 4-year-old daughter, and I are looking for our next family-friendly weekend trip or dinner spot near {location}.
                Here are our most recent outings: {recent_trips}
                Suggest 3 NEW, highly-rated local places. DO NOT suggest overlapping cuisines/places.
                """
                with st.spinner("Finding fresh recommendations..."):
                    model = genai.GenerativeModel("gemini-1.5-flash")
                    response = model.generate_content(prompt)
                    st.markdown(response.text)
            except Exception as e:
                st.error(f"An API error occurred: {e}")