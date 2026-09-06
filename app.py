import streamlit as st
import pandas as pd
from google import genai
import os
import time
from datetime import date
from streamlit_gsheets import GSheetsConnection
from streamlit_searchbox import st_searchbox

TRIPS_WORKSHEET = "Trips"
WISHLIST_WORKSHEET = "Wishlist"

TRIPS_COLUMNS = ["Date", "Place Name", "Cuisine/Activity", "Rating", "Notes", "Lat", "Lon"]
WISHLIST_COLUMNS = ["Added Date", "Place Name", "Cuisine/Activity", "Notes"]

st.set_page_config(page_title="Family Trip Planner", page_icon="🚗", layout="centered")
st.title("🚗 Family Trip & Dinner Planner")

# --- Google Sheets connection (shared store for both of us) ---
conn = st.connection("gsheets", type=GSheetsConnection)

def load_sheet(worksheet, columns):
    try:
        sheet_df = conn.read(worksheet=worksheet, ttl=0)
        sheet_df = sheet_df.dropna(how="all")  # drop blank trailing rows Sheets sometimes returns
        for col in columns:
            if col not in sheet_df.columns:
                sheet_df[col] = None
        # Backward compatibility: an earlier version of this sheet split ratings
        # into "Dad's Rating" / "Mum's Rating" — fold that back into one Rating.
        if worksheet == TRIPS_WORKSHEET and "Dad's Rating" in sheet_df.columns and sheet_df["Rating"].isna().all():
            sheet_df["Rating"] = sheet_df["Dad's Rating"]
        return sheet_df[columns]
    except Exception:
        # Empty/brand-new sheet, or the worksheet doesn't exist yet
        return pd.DataFrame(columns=columns)

def save_sheet(worksheet, sheet_df):
    conn.update(worksheet=worksheet, data=sheet_df)

def geocode_place(place_name):
    """Best-effort free geocoding via OpenStreetMap/Nominatim, worldwide. Returns (lat, lon) or (None, None)."""
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="family-trip-planner-app")
        result = geolocator.geocode(place_name, timeout=10)
        if result:
            return result.latitude, result.longitude
    except Exception:
        pass
    return None, None

def search_places(searchterm):
    """Powers the autocomplete box: free, worldwide place search via OpenStreetMap/Nominatim.
    Always includes a 'use as typed' option so obscure places with no match can still be logged."""
    if not searchterm:
        return []
    options = [(f'✏️ Use "{searchterm}" as typed', searchterm)]
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="family-trip-planner-app")
        results = geolocator.geocode(searchterm, exactly_one=False, limit=5, timeout=10)
        if results:
            for r in results:
                short_name = r.address.split(",")[0].strip()
                options.append((r.address, short_name))
    except Exception:
        pass
    return options

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

trips_df = load_sheet(TRIPS_WORKSHEET, TRIPS_COLUMNS)
wishlist_df = load_sheet(WISHLIST_WORKSHEET, WISHLIST_COLUMNS)

tab_log, tab_past, tab_bulk, tab_wishlist, tab_map, tab_ai = st.tabs([
    "📝 Log a Trip", "📅 Past Trips", "📋 Bulk Add", "⭐ Wishlist", "🗺️ Map", "✨ AI Suggestions",
])

# ---------------------------------------------------------------------------
with tab_log:
    st.subheader("Add a New Trip or Dinner")

    place_name = st_searchbox(
        search_places,
        placeholder="Start typing a place name, anywhere in the world...",
        label="Place Name",
        key="place_searchbox",
    )

    with st.form("add_trip_form", clear_on_submit=True):
        trip_date = st.date_input("Date", date.today())
        cuisine = st.text_input("Cuisine or Activity")
        rating = st.slider("Rating", 1, 5, 3)
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Save Entry")

        if submitted:
            if not place_name:
                st.error("Search and select a place name above first.")
            elif not cuisine:
                st.error("Please fill out the Cuisine/Activity field.")
            else:
                lat, lon = geocode_place(place_name)
                new_entry = pd.DataFrame([{
                    "Date": str(trip_date),
                    "Place Name": place_name,
                    "Cuisine/Activity": cuisine,
                    "Rating": rating,
                    "Notes": notes,
                    "Lat": lat,
                    "Lon": lon,
                }])
                updated_df = pd.concat([trips_df, new_entry], ignore_index=True)
                save_sheet(TRIPS_WORKSHEET, updated_df)
                st.success(f"Successfully added '{place_name}'!")
                st.rerun()

# ---------------------------------------------------------------------------
with tab_past:
    st.subheader("Our Travel & Dining History")
    if trips_df.empty:
        st.info("No trips logged yet.")
    else:
        search_col, rating_col = st.columns([2, 1])
        with search_col:
            search = st.text_input("🔍 Search by place or cuisine")
        with rating_col:
            min_rating = st.slider("Min. Rating", 1, 5, 1)

        display_df = trips_df.copy()
        display_df["Rating"] = pd.to_numeric(display_df["Rating"], errors="coerce")
        if search:
            mask = (
                display_df["Place Name"].str.contains(search, case=False, na=False)
                | display_df["Cuisine/Activity"].str.contains(search, case=False, na=False)
            )
            display_df = display_df[mask]
        display_df = display_df[display_df["Rating"].fillna(0) >= min_rating]

        view_cols = [c for c in TRIPS_COLUMNS if c not in ("Lat", "Lon")]
        st.dataframe(
            display_df.sort_values(by="Date", ascending=False)[view_cols],
            use_container_width=True,
        )

        with st.expander("✏️ Edit or delete entries"):
            st.caption("Edit any cell directly, or use the row menu to delete a row, then save.")
            edited_df = st.data_editor(
                trips_df.sort_values(by="Date", ascending=False),
                num_rows="dynamic",
                use_container_width=True,
                key="trips_data_editor",
            )
            if st.button("💾 Save changes", key="save_trips_edit"):
                save_sheet(TRIPS_WORKSHEET, edited_df[TRIPS_COLUMNS])
                st.success("Changes saved!")
                st.rerun()

# ---------------------------------------------------------------------------
with tab_bulk:
    st.subheader("Add Several Trips at Once")
    st.caption(
        "Handy for backfilling old trips from memory. One place per line, format: "
        "`Place Name, Cuisine/Activity, Rating, Notes` — rating and notes are optional."
    )
    bulk_text = st.text_area(
        "Paste your list here",
        height=200,
        placeholder="The Ivy, British, 5, Lovely Sunday lunch\nCadbury World, Family Activity, 4",
    )

    if st.button("Add these trips"):
        if not bulk_text.strip():
            st.warning("Paste at least one line first.")
        else:
            new_rows, skipped = [], []
            for i, line in enumerate(bulk_text.strip().splitlines(), start=1):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2 or not parts[0] or not parts[1]:
                    skipped.append(i)
                    continue
                new_rows.append({
                    "Date": str(date.today()),
                    "Place Name": parts[0],
                    "Cuisine/Activity": parts[1],
                    "Rating": parts[2] if len(parts) > 2 and parts[2] else "",
                    "Notes": ", ".join(parts[3:]) if len(parts) > 3 else "",
                    "Lat": None,
                    "Lon": None,
                })
            if new_rows:
                updated_df = pd.concat([trips_df, pd.DataFrame(new_rows)], ignore_index=True)
                save_sheet(TRIPS_WORKSHEET, updated_df)
                st.success(f"Added {len(new_rows)} trip(s)!")
                if skipped:
                    st.warning(f"Skipped line(s) {skipped} — need at least a place name and cuisine/activity.")
                st.rerun()
            else:
                st.error("Nothing valid to add — check the format and try again.")

# ---------------------------------------------------------------------------
with tab_wishlist:
    st.subheader("Places We Want to Try")
    with st.form("add_wishlist_form"):
        w_place = st.text_input("Place Name")
        w_cuisine = st.text_input("Cuisine or Activity")
        w_notes = st.text_area("Why we want to go / who recommended it")
        w_submitted = st.form_submit_button("Add to Wishlist")

        if w_submitted:
            if w_place:
                new_entry = pd.DataFrame([{
                    "Added Date": str(date.today()),
                    "Place Name": w_place,
                    "Cuisine/Activity": w_cuisine,
                    "Notes": w_notes,
                }])
                updated_wishlist = pd.concat([wishlist_df, new_entry], ignore_index=True)
                save_sheet(WISHLIST_WORKSHEET, updated_wishlist)
                st.success(f"Added '{w_place}' to the wishlist!")
                st.rerun()
            else:
                st.error("Please enter a place name.")

    st.divider()
    if wishlist_df.empty:
        st.info("Your wishlist is empty — add somewhere you'd like to try above.")
    else:
        st.caption("Delete a row (e.g. once you've finally been) and save to update the list.")
        edited_wishlist = st.data_editor(
            wishlist_df.sort_values(by="Added Date", ascending=False),
            num_rows="dynamic",
            use_container_width=True,
            key="wishlist_editor",
        )
        if st.button("💾 Save wishlist changes"):
            save_sheet(WISHLIST_WORKSHEET, edited_wishlist[WISHLIST_COLUMNS])
            st.success("Wishlist updated!")
            st.rerun()

# ---------------------------------------------------------------------------
with tab_map:
    st.subheader("Where We've Been")

    if trips_df.empty:
        st.info("No trips logged yet.")
    else:
        needs_lat = pd.to_numeric(trips_df["Lat"], errors="coerce").isna()
        missing = trips_df[needs_lat]

        if not missing.empty:
            st.info(f"{len(missing)} place(s) don't have map coordinates yet.")
            if st.button("📍 Locate missing places"):
                updated_df = trips_df.copy()
                progress = st.progress(0.0)
                located = 0
                for i, (idx, row) in enumerate(missing.iterrows()):
                    lat, lon = geocode_place(row["Place Name"])
                    if lat is not None:
                        updated_df.at[idx, "Lat"] = lat
                        updated_df.at[idx, "Lon"] = lon
                        located += 1
                    progress.progress((i + 1) / len(missing))
                    time.sleep(1)  # be polite to the free geocoding service
                save_sheet(TRIPS_WORKSHEET, updated_df)
                st.success(f"Located {located} of {len(missing)} place(s).")
                st.rerun()

        mappable = trips_df.copy()
        mappable["Lat"] = pd.to_numeric(mappable["Lat"], errors="coerce")
        mappable["Lon"] = pd.to_numeric(mappable["Lon"], errors="coerce")
        mappable = mappable.dropna(subset=["Lat", "Lon"])
        if mappable.empty:
            st.info("No mapped places yet — click 'Locate missing places' above once you've logged a few trips.")
        else:
            st.map(mappable.rename(columns={"Lat": "lat", "Lon": "lon"})[["lat", "lon"]])

# ---------------------------------------------------------------------------
with tab_ai:
    st.subheader("Surprise Us!")
    location = st.text_input(
        "Where are we looking?",
        value="",
        placeholder="e.g. Cambridge, UK or Lisbon, Portugal — anywhere",
    )

    if st.button("Get AI Suggestions ✨"):
        if not api_key:
            st.error("Gemini API Key not found in Streamlit Secrets.")
        elif trips_df.empty:
            st.warning("Log at least one past trip first.")
        elif not location:
            st.warning("Please enter a location to search near.")
        else:
            try:
                client = genai.Client(api_key=api_key)

                t_df = trips_df.copy()
                t_df["Rating"] = pd.to_numeric(t_df["Rating"], errors="coerce")

                loved = t_df[t_df["Rating"] >= 4]
                mixed = t_df[t_df["Rating"] == 3]
                disliked = t_df[t_df["Rating"] <= 2]

                def format_trips(sub_df):
                    if sub_df.empty:
                        return "None yet."
                    lines = []
                    for _, row in sub_df.iterrows():
                        note = row.get("Notes")
                        note_str = f" — {note}" if pd.notna(note) and str(note).strip() else ""
                        lines.append(f"- {row['Place Name']} ({row['Cuisine/Activity']}, rated {row['Rating']}/5){note_str}")
                    return "\n".join(lines)

                wishlist_str = (
                    "\n".join(f"- {r['Place Name']} ({r['Cuisine/Activity']})" for _, r in wishlist_df.iterrows())
                    if not wishlist_df.empty else "None."
                )

                prompt = f"""
                You know our family well: me, my wife, and our 4-year-old daughter. We're looking for our next family-friendly trip or dinner spot near {location}.

                Places and activities we've LOVED before (high ratings):
                {format_trips(loved)}

                Places that were just OK (middle ratings):
                {format_trips(mixed)}

                Places that DIDN'T work for us (low ratings) — avoid similar picks:
                {format_trips(disliked)}

                Places already on our wishlist (don't suggest these, we already know about them):
                {wishlist_str}

                Based on this feedback, suggest 3 NEW places or activities near {location} that we haven't already tried and that aren't already on our wishlist. For each one, write a short, warm, personal note — like a friend who knows our family — explaining specifically why it fits what we've enjoyed before and how it avoids what didn't work for us. DO NOT suggest overlapping cuisines/places we've already been to or already plan to try.
                """
                with st.spinner("Finding fresh recommendations..."):
                    response = client.models.generate_content(
                        model='gemini-3.6-flash',
                        contents=prompt,
                    )
                    st.markdown(response.text)
            except Exception as e:
                st.error(f"An API error occurred: {e}")