from flask import Flask, render_template, jsonify, request  # Web framework
import feedparser  # Used to parse RSS feeds
from bs4 import BeautifulSoup  # Helps to extract data from HTML/XML
from datetime import datetime  # To work with dates and times
import pytz  # For handling different time zones
import folium  # Library to create interactive maps
from folium.plugins import FloatImage  # To add images (the legend) on folium maps
import requests  # To make HTTP requests (to geolocation API)
import os  # To interact with environment variables
from dotenv import load_dotenv  # To load environment variables from a .env file

# Initialise the Flask app
app = Flask(__name__)

# Load environment variables from the .env file
load_dotenv()

# Retrieve HERE API key from environment variables (used for geocoding)
HERE_API_KEY = os.getenv('HERE_API_KEY')

# Raise an error if the API key is missing
if not HERE_API_KEY:
    raise ValueError("Missing HERE API Key. Ensure it is set in environment variables.")

# URL for the RSS feed with incident data (like fire events)
RSS_FEED_URL = "https://data.emergency.vic.gov.au/Show?pageId=getIncidentRSS"

# Function to convert UTC time to Australian Eastern Daylight Time (AEDT)
def convert_to_aedt(utc_time_str):
    # Parse the time string and convert to datetime object
    utc_time = datetime.strptime(utc_time_str, '%a, %d %b %Y %H:%M:%S %Z')
    utc_zone = pytz.timezone('UTC')  # Define the UTC timezone
    utc_time = utc_zone.localize(utc_time)  # Localise to UTC timezone
    aedt_zone = pytz.timezone('Australia/Melbourne')  # Define AEDT timezone
    aedt_time = utc_time.astimezone(aedt_zone)  # Convert UTC time to AEDT
    # Return the time in a readable string format
    return aedt_time.strftime('%d/%m/%Y %H:%M:%S AEDT')

# Function to extract incident data from the RSS feed
def get_incidents_from_rss():
    incidents = []  # Initialise an empty list to store incidents
    feed = feedparser.parse(RSS_FEED_URL)  # Parse the RSS feed
    # Loop through each incident in the feed
    for entry in feed.entries:
        incident_name = entry.get('title', 'N/A')  # Get the incident title
        date_time = entry.get('published', 'N/A')  # Get the published time
        date_time_aedt = convert_to_aedt(date_time) if date_time != 'N/A' else 'N/A'  # Convert time to AEDT
        
        # Extract other incident details (location, size, vehicles, etc.)
        summary_html = entry.get('summary', '')
        soup = BeautifulSoup(summary_html, 'html.parser')  # Parse the HTML summary
        fire_district = soup.find(string="Fire District:").find_next('br').previous_element.strip()
        incident_no = soup.find(string="Incident No:").find_next('br').previous_element.strip()
        incident_type = soup.find(string="Type:").find_next('br').previous_element.strip()
        location = soup.find(string="Location:").find_next('br').previous_element.strip()
        status = soup.find(string="Status:").find_next('br').previous_element.strip()
        size = soup.find(string="Size:").find_next('br').previous_element.strip()
        vehicles = soup.find(string="Vehicles:").find_next('br').previous_element.strip()
        latitude = soup.find(string="Latitude:").find_next('br').previous_element.strip()
        longitude = soup.find(string="Longitude:").find_next('br').previous_element.strip()

        # If the incident has valid coordinates (latitude, longitude), add it to the list
        if latitude and longitude:
            incidents.append({
                "Incident Name": incident_name,
                "Fire District": fire_district,
                "Incident No": incident_no,
                "Date/Time": date_time_aedt,
                "Type": incident_type,
                "Location": location,
                "Status": status,
                "Size": size,
                "Vehicles": vehicles,
                "Latitude": latitude,
                "Longitude": longitude
            })
    return incidents  # Return the list of incidents

# Route to get incidents as a JSON response (for API)
@app.route("/get_incidents")
def get_incidents_route():
    incidents = get_incidents_from_rss()  # Call the function to get incidents
    return jsonify(incidents)  # Return the incidents in JSON format

# Route to search for incidents by postcode
@app.route("/search_postcode", methods=['POST'])
def search_postcode():
    postcode = request.form.get('postcode')  # Get the postcode from the form data
    if not postcode:
        return jsonify({'error': 'Postcode is required'}), 400  # Return an error if no postcode

    # Call HERE API to get location data for the given postcode
    url = f'https://geocode.search.hereapi.com/v1/geocode?q={postcode}&apiKey={HERE_API_KEY}'
    response = requests.get(url)

    if response.status_code != 200:
        return jsonify({'error': 'Failed to fetch data from HERE API'}), response.status_code  # Error if API fails

    data = response.json()  # Parse the response as JSON

    # Check if valid data was returned and extract the first result
    if data and 'items' in data and len(data['items']) > 0:
        location_data = data['items'][0]
        address = location_data.get('address', {})
        state = address.get('state', '')
        country = address.get('countryCode', '')
        coordinates = location_data['position']

        # Ensure the location is in Victoria, Australia
        if country != 'AUS' or state != 'Victoria':
            return jsonify({'error': 'Invalid Postcode, try suburb name instead'}), 400

        # Create a map with the location of the postcode
        mapObj = folium.Map(location=[coordinates['lat'], coordinates['lng']], zoom_start=12, tiles=None)

        # Add different layers and markers for incidents to the map
        default_layer = folium.TileLayer(
            tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attr='&copy; OpenStreetMap contributors',
            name='Default'
        ).add_to(mapObj)

        # Get incidents and add them as markers to the map
        incidents = get_incidents_from_rss()
        for incident in incidents:
            lat = incident["Latitude"]
            lon = incident["Longitude"]

            if lat and lon:
                try:
                    lat = float(lat)
                    lon = float(lon)
                except ValueError:
                    continue

                # Set marker colour based on incident status
                if incident["Status"] == "Safe":
                    icon_color = 'green'
                elif incident["Status"] in ["Responding", "Under Control"]:
                    icon_color = 'orange'
                else:
                    icon_color = 'red'

                # Create a popup with incident details
                popup_content = (
                    f"<strong>Incident Name:</strong> {incident['Incident Name']}<br>"
                    f"<strong>Status:</strong> {incident['Status']}<br>"
                    f"<strong>Size:</strong> {incident['Size']}<br>"
                    f"<strong>Location:</strong> {incident['Location']}<br>"
                    f"<strong>Date/Time:</strong> {incident['Date/Time']}<br>"
                )
                folium.Marker(
                    location=[lat, lon],
                    popup=folium.Popup(popup_content, max_width=300),
                    icon=folium.Icon(color=icon_color, icon='fire', prefix='fa', icon_color='white')
                ).add_to(mapObj)

        # Add the legend and layer control to the map
        folium.Marker(
            location=[coordinates['lat'], coordinates['lng']],
            popup=f"<strong>{address['label']}</strong>",
            icon=folium.Icon(color='blue')
        ).add_to(mapObj)

        FloatImage('/static/legend.png', bottom=1, left=0.4).add_to(mapObj)
        folium.LayerControl('topleft').add_to(mapObj)

        iframe = mapObj.get_root()._repr_html_()  # Get the map as HTML

        # Return the map and location data as JSON
        return jsonify({
            'latitude': coordinates['lat'],
            'longitude': coordinates['lng'],
            'address': address['label'],
            'map_iframe': iframe
        })

    else:
        return jsonify({'error': 'No data found for the given postcode'}), 404  # Error if no data found

# Route for the home page to display the main map
@app.route("/")
def home():
    # Create a map centered on Victoria
    mapObj = folium.Map(location=[-37.4713, 144.7852], zoom_start=7, tiles=None)

    # Add layers to the map (satellite and default)
    satellite_layer = folium.TileLayer(
        tiles='https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        attr='&copy; OpenTopoMap contributors',
        name='Satellite'
    ).add_to(mapObj)

    default_layer = folium.TileLayer(
        tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attr='&copy; OpenStreetMap contributors',
        name='Default'
    ).add_to(mapObj)

    # Add a layer control to toggle between satellite/default layers
    folium.LayerControl('topleft').add_to(mapObj)

    # Add markers for all incidents
    incidents = get_incidents_from_rss()
    for incident in incidents:
        lat = incident["Latitude"]
        lon = incident["Longitude"]

        if lat and lon:
            try:
                lat = float(lat)
                lon = float(lon)
            except ValueError:
                continue

            # Set the marker colour based on incident status
            if incident["Status"] == "Safe":
                icon_color1 = 'green'
            elif incident["Status"] in ["Responding", "Under Control"]:
                icon_color1 = 'orange'
            else:
                icon_color1 = 'red'

            # Create a popup with detailed incident info
            popup_content = (
                f"<strong>Incident Name:</strong> {incident['Incident Name']}<br>"
                f"<strong>Type:</strong> {incident['Type']}<br>"
                f"<strong>Status:</strong> {incident['Status']}<br>"
                f"<strong>Size:</strong> {incident['Size']}<br>"
                f"<strong>Vehicles:</strong> {incident['Vehicles']}<br>"
                f"<strong>Location:</strong> {incident['Location']}<br>"
                f"<strong>Fire District:</strong> {incident['Fire District']}<br>"
                f"<strong>Incident No:</strong> {incident['Incident No']}<br>"
                f"<strong>Date/Time:</strong> {incident['Date/Time']}<br>"
            )
            # Folium marker styling
            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup_content, max_width=300),
                icon=folium.Icon(color=icon_color1, icon='fire', prefix='fa', icon_color='white')
            ).add_to(mapObj)

    # Add the image legend and set map position
    image_file = '/static/legend.png'
    FloatImage(image_file, bottom=1, left=0.4).add_to(mapObj)

    mapObj.get_root().width = "100%"
    mapObj.get_root().height = "100%"

    iframe = mapObj.get_root()._repr_html_()  # Get the map as HTML iframe

    # Render the map on the home page
    return render_template('map.html', iframe=iframe)


# Run the Flask app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=50100, debug=True) 