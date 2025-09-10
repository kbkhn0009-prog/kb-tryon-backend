import os
import io
import time
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": [
    "https://www.karlbarbini.ru",
    "https://kbkhn0009-prog.github.io",
    "http://localhost:5500",  # для локальных тестов
    "http://127.0.0.1:5500"
]}})

API_KEY = os.getenv("FACE_API_KEY")  # ключ Deep-Image

BASE_IMAGES = {
    "black": "https://www.karlbarbini.ru/assets/black1.jpg",
    "white": "https://www.karlbarbini.ru/assets/white1.jpg",
}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/tryon")
def tryon():
    try:
        if "photo" not in request.files:
            return jsonify({"error": "Отсутствует файл photo"}), 400

        photo = request.files["photo"]
        dress = (request.form.get("dress") or "black").lower()
        contact = (request.form.get("contact") or "").strip()

        if dress not in BASE_IMAGES:
            return jsonify({"error": "Некорректное значение dress"}), 400

        target_url = BASE_IMAGES[dress]

        headers = {"x-api-key": API_KEY}

        # --- Шаг 1. Запускаем обработку ---
        process_url = "https://deep-image.ai/rest_api/process"
        files = {"file": (photo.filename, photo.stream, photo.mimetype)}
        data = {
            "enhancements": ["denoise", "deblur", "light"],
            "url": target_url,
            "width": 2000
        }

        r1 = requests.post(process_url, headers=headers, files=files, data={"parameters": str(data)}, timeout=120)
        if r1.status_code >= 400:
            return jsonify({"error": f"Face API process error {r1.status_code}", "details": r1.text}), 502

        job = r1.json()
        job_id = job.get("id")
        if not job_id:
            return jsonify({"error": "API не вернул job_id", "raw": job}), 502

        # --- Шаг 2. Ждём результат ---
        result_url = "https://deep-image.ai/rest_api/process_result"
        output_url = None
        for _ in range(10):  # до 10 попыток
            r2 = requests.post(result_url, headers=headers, json={"id": job_id}, timeout=60)
            if r2.status_code >= 400:
                return jsonify({"error": f"Face API result error {r2.status_code}", "details": r2.text}), 502

            result = r2.json()
            output_url = result.get("url")
            if output_url:
                break
            time.sleep(3)  # подождём немного, пока обработка закончится

        if not output_url:
            return jsonify({"error": "API не вернул ссылку на результат", "raw": result}), 502

        # --- Отправка админу в Telegram ---
        if TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID:
            try:
                caption = f"Виртуальная примерка ({dress}). Контакт: {contact}"
                tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                img = requests.get(output_url, timeout=60).content
                requests.post(tg_url, data={"chat_id": TELEGRAM_ADMIN_CHAT_ID, "caption": caption},
                              files={"photo": img}, timeout=60)
            except Exception as e:
                print("Telegram send error:", e)

        return jsonify({"output_url": output_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)


