from fleet.config import ROOT

VEHICLE_ID = "CD-006"
VEHICLE_DETAILS = {
    "Make": "MINI",
    "Model": "Cooper",
    "Colour": "Green",
    "Registration": "YK23 LZP",
    "Powertrain": "Petrol",
    "City": "Stornoway",
    "RegisterVersion": 3,
}
PHOTO = ROOT / "media" / "crash1.png"
DESCRIPTION = "I scraped the front bumper while parking. The photograph shows the affected area."
CUSTOMER_NAME = "Alex Morgan"
CUSTOMER_EMAIL = "alex.morgan@example.com"
POSITION = {"Latitude": 58.2094, "Longitude": -6.3857, "RouteId": "STY-PARKED"}
POSITION_KEY = f"vehicle-position/{VEHICLE_ID}/{VEHICLE_DETAILS['RegisterVersion']}"
