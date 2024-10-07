from flask import Flask, render_template, jsonify, request
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime
import pytz
import folium
from folium.plugins import FloatImage
import requests
import os
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()

HERE_API_KEY = os.getenv('HERE_API_KEY')

if not HERE_API_KEY:
    raise ValueError("Missing HERE API Key. Ensure it is set in environment variables.")

RSS_FEED_URL = "https://data.emergency.vic.gov.au/Show?pageId=getIncidentRSS"

def convert_to_aedt(utc_time_str):
    utc_time = datetime.strptime(utc_time_str, '%a, %d %b %Y %H:%M:%S %Z')
    utc_zone = pytz.timezone('UTC')
    utc_time = utc_zone.localize(utc_time)
    aedt_zone = pytz.timezone('Australia/Melbourne')
    aedt_time = utc_time.astimezone(aedt_zone)
    return aedt_time.strftime('%d/%m/%Y %H:%M:%S AEDT')

def get_incidents_from_rss():
    incidents = []
    feed = feedparser.parse(RSS_FEED_URL)
    for entry in feed.entries:
        incident_name = entry.get('title', 'N/A')
        date_time = entry.get('published', 'N/A')
        date_time_aedt = convert_to_aedt(date_time) if date_time != 'N/A' else 'N/A'
        summary_html = entry.get('summary', '')
        soup = BeautifulSoup(summary_html, 'html.parser')
        fire_district = soup.find(string="Fire District:").find_next('br').previous_element.strip()
        incident_no = soup.find(string="Incident No:").find_next('br').previous_element.strip()
        incident_type = soup.find(string="Type:").find_next('br').previous_element.strip()
        location = soup.find(string="Location:").find_next('br').previous_element.strip()
        status = soup.find(string="Status:").find_next('br').previous_element.strip()
        size = soup.find(string="Size:").find_next('br').previous_element.strip()
        vehicles = soup.find(string="Vehicles:").find_next('br').previous_element.strip()
        latitude = soup.find(string="Latitude:").find_next('br').previous_element.strip()
        longitude = soup.find(string="Longitude:").find_next('br').previous_element.strip()

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
    return incidents

@app.route("/get_incidents")
def get_incidents_route():
    incidents = get_incidents_from_rss()
    return jsonify(incidents)

@app.route("/search_postcode", methods=['POST'])
def search_postcode():
    postcode = request.form.get('postcode')
    if not postcode:
        return jsonify({'error': 'Postcode is required'}), 400

    url = f'https://geocode.search.hereapi.com/v1/geocode?q={postcode}&apiKey={HERE_API_KEY}'
    response = requests.get(url)

    if response.status_code != 200:
        return jsonify({'error': 'Failed to fetch data from HERE API'}), response.status_code

    data = response.json()

    if data and 'items' in data and len(data['items']) > 0:
        # Extracting the first result
        location_data = data['items'][0]
        address = location_data.get('address', {})
        state = address.get('state', '')
        country = address.get('countryCode', '')
        coordinates = location_data['position']

        # Check if the result is within Victoria, Australia
        if country != 'AUS' or state != 'Victoria':
            return jsonify({'error': 'Invalid Postcode, try suburb name instead'}), 400

        # If valid, proceed with creating the map
        mapObj = folium.Map(location=[coordinates['lat'], coordinates['lng']], zoom_start=12, tiles=None)

        default_layer = folium.TileLayer(
            tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
            attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            name='Default'
        ).add_to(mapObj)

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

                if incident["Status"] == "Safe":
                    icon_color = 'green'
                elif incident["Status"] in ["Responding", "Under Control"]:
                    icon_color = 'orange'
                else:
                    icon_color = 'red'

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

        folium.Marker(
            location=[coordinates['lat'], coordinates['lng']],
            popup=f"<strong>{address['label']}</strong>",
            icon=folium.Icon(color='blue')
        ).add_to(mapObj)

        FloatImage('/static/legend.png', bottom=1, left=0.4).add_to(mapObj)

        folium.LayerControl('topleft').add_to(mapObj)

        iframe = mapObj.get_root()._repr_html_()

        return jsonify({
            'latitude': coordinates['lat'],
            'longitude': coordinates['lng'],
            'address': address['label'],
            'map_iframe': iframe
        })

    else:
        return jsonify({'error': 'No data found for the given postcode'}), 404

@app.route("/")
def home():
    mapObj = folium.Map(location=[-37.4713, 144.7852], zoom_start=7, tiles=None)

    satellite_layer = folium.TileLayer(
        tiles='https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
        attr='&copy; <a href="https://opentopomap.org">OpenTopoMap</a> contributors',
        name='Satellite'
    ).add_to(mapObj)

    default_layer = folium.TileLayer(
        tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        name='Default'
    ).add_to(mapObj)

    folium.LayerControl('topleft').add_to(mapObj)

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

            if incident["Status"] == "Safe":
                icon_color1 = 'green'
            elif incident["Status"] in ["Responding", "Under Control"]:
                icon_color1 = 'orange'
            else:
                icon_color1 = 'red'

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

            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(popup_content, max_width=300),
                icon=folium.Icon(color=icon_color1, icon='fire', prefix='fa', icon_color='white')
            ).add_to(mapObj)

    image_file = '/static/legend.png'
    FloatImage(image_file, bottom=1, left=0.4).add_to(mapObj)

    mapObj.get_root().width = "100%"
    mapObj.get_root().height = "100%"

    iframe = mapObj.get_root()._repr_html_()

    return render_template('map.html', iframe=iframe)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=50100, debug=True)
