import requests

url = "https://datalens.yandex/charts/api/run"

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain",
    "Origin": "https://datalens.yandex",
    "Referer": "https://datalens.yandex/6dr39r9a9l9mt?state=228a5e4d170",
    "x-dl-component": "ui",
    "x-dash-info": "dashId6dr39r9a9l9mtdashTabIdZa",
    "x-dl-display-mode": "basic",
    # сюда добавить Cookie из браузера
    # "Cookie": "yasc=...; ymisad=...; gdpr=0; ymd=...; ymuid=..."
}

payload = {
    "id": "jsaobu3lpeos6",
    "params": {
        "klub_77wt": "",
        "data_v9da": "__interval_2023-01-01T00:00:00.000Z___relative_-0d",
        "igrok_4vy1": "Бабаев Михаил",
        "uchastnik_0zyi": "Бабаев Михаил",
    },
    "widgetConfig": {"actionParams": {"enable": True}},
    "responseOptions": {"includeConfig": True, "includeLogs": False},
}

r = requests.post(url, json=payload, headers=headers, timeout=60)
r.raise_for_status()
print(r.json())
