from datetime import datetime
import time

from ConsoApi import ConsoApi
from TokenManager import TokenManager


# Get tokens
token_manager = TokenManager(force_refresh=False)

consoapi = ConsoApi(token_manager)

def print_conso_data(data, type):
    if data is None:
        print(f"[{type}] No data received.")
        return

    totalKwh = 0
    for record in data.get("consommations", []):
        # convert 2025-04-01T00:00:00 to date object
        date = record.get("date")
        date_obj = datetime.strptime(date, "%Y-%m-%dT%H:%M:%S").date()

        date_str = date_obj.strftime("%d/%m/%Y")
        value = record.get("valeur")
        # 1000 Kwh = 96€
        price = (value / 1000) * 96
        totalKwh += value
        print(f"[{type}] Date: {date_str}, Value: {value} Kwh, Price: {price:.2f} €")

    totalPrice = (totalKwh / 1000) * 96
    print(f"[{type}] Total consumption: {totalKwh} Kwh, Total price: {totalPrice:.2f} €")

while True:
    # Get first day of month
    from_date = datetime.now().replace(day=1).strftime("%Y-%m-%dT00:00:00")
    # Get last day of month
    to_date = datetime.now().strftime("%Y-%m-%dT23:59:59")

    print("Fetching conso data...")
    print_conso_data(consoapi.get_conso_chauffage(from_date, to_date), "🌡")
    print_conso_data(consoapi.get_conso_eau_chaude(from_date, to_date), "🚿")

    #Add 5min delay
    print("Next fetch in 5 min...")
    time.sleep(300)



