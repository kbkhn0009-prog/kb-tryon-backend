import os
import uuid
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": [
    "https://www.karlbarbini.ru",
    "https://kbkhn0009-prog.github.io",
    "http://localhost:5500",   # для локальных тестов
    "http://127.0.0.1:5500"
]}})

# === Конфиг ===
API_URL = os.getenv("FACE_API_URL", "https://deep-image.ai/rest_api/process_result")
API_KEY = os.getenv("FACE_API_KEY", "YOUR_API_KEY")

BASE_IMAGES = {
    "black": "https://www.karlbarbini.ru/assets/black1.jpg",
    "white": "https://www.karlbarbini.ru/assets/white1.jpg",
}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.get("/health")
def health():
    return {"ok": True}


# Отдаём загруженные фото клиенток (для deep-image.ai нужно URL)
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


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

        # Сохраняем фото клиентки в /uploads с уникальным именем
        ext = os.path.splitext(photo.filename)[1]
        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        photo.save(filepath)

        # Публичный URL для deep-image.ai
        host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost:3000")
        client_url = f"https://{host}/uploads/{filename}"

        # Запрос к deep-image.ai
        payload = {
            "url": target_url,  # фото модели в платье
            "background": {
                "generate": {
                    "strength": 0.1,
                    "adapter_type": "face",
                    "avatar_generation_type": "creative_img2img",
                    "ip_image2": client_url  # фото клиентки
                }
            }
        }

        headers = {
            "Content-Type": "application/json",
            "x-api-key": API_KEY
        }

        r = requests.post(API_URL, headers=headers, json=payload, timeout=120)
        if r.status_code >= 400:
            return jsonify({"error": f"Face API error {r.status_code}", "details": r.text}), 502

        result = r.json()
        output_url = result.get("url") or result.get("output_url") or result.get("result_url")
        if not output_url:
            return jsonify({"error": "API не вернул ссылку на результат", "raw": result}), 502

        # Отправка админу в Telegram (опционально)
        if TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID:
            try:
                caption = f"Виртуальная примерка ({dress}). Контакт: {contact}"
                tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                img = requests.get(output_url, timeout=60).content
                requests.post(
                    tg_url,
                    data={"chat_id": TELEGRAM_ADMIN_CHAT_ID, "caption": caption},
                    files={"photo": img},
                    timeout=60
                )
            except Exception as e:
                print("Telegram send error:", e)

        return jsonify({"output_url": output_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)

