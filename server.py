import os
import uuid
import csv
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": [
    "https://www.karlbarbini.ru",
    "https://karlbarbini.ru",   # добавили домен без www
    "https://kbkhn0009-prog.github.io",
    "http://localhost:5500",
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
RESULTS_FOLDER = "results"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

CLIENTS_CSV = "clients.csv"


@app.get("/health")
def health():
    return {"ok": True}


# Раздаём загруженные фото клиенток
@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# Раздаём результаты с водяным знаком
@app.route("/results/<filename>")
def result_file(filename):
    return send_from_directory(RESULTS_FOLDER, filename)


@app.post("/api/tryon")
def tryon():
    try:
        if "photo" not in request.files:
            return jsonify({"error": "Отсутствует файл photo"}), 400

        photo = request.files["photo"]
        dress = (request.form.get("dress") or "black").lower()
        contact = (request.form.get("contact") or "").strip()

        # === Ограничение размера файла (5 MB) ===
        photo.stream.seek(0, os.SEEK_END)
        size_mb = photo.stream.tell() / (1024 * 1024)
        photo.stream.seek(0)
        if size_mb > 5:
            return jsonify({"error": "Фото слишком большое. Максимум 5 МБ."}), 400

        if dress not in BASE_IMAGES:
            return jsonify({"error": "Некорректное значение dress"}), 400

        target_url = BASE_IMAGES[dress]

        # Сохраняем фото клиентки
        ext = os.path.splitext(photo.filename)[1] or ".jpg"
        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        photo.save(filepath)

        # Публичный URL для deep-image.ai
        host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "localhost:3000")
        client_url = f"https://{host}/uploads/{filename}"

        # Запрос в deep-image.ai
        payload = {
            "url": target_url,
            "background": {
                "generate": {
                    "strength": 0.1,
                    "adapter_type": "face",
                    "avatar_generation_type": "creative_img2img",
                    "ip_image2": client_url
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

        # === Накладываем водяной знак ===
        wm_filename = f"wm_{uuid.uuid4().hex}.jpg"
        wm_path = os.path.join(RESULTS_FOLDER, wm_filename)

        try:
            img_bytes = requests.get(output_url, timeout=60).content
            img = Image.open(BytesIO(img_bytes)).convert("RGBA")

            # надпись Karl Barbini внизу
            draw = ImageDraw.Draw(img)
            font = ImageFont.load_default()
            text = "KARL BARBINI"
            w, h = img.size
            tw, th = draw.textsize(text, font=font)
            draw.text((w - tw - 20, h - th - 20), text, font=font, fill=(201, 162, 84, 255))

            img.save(wm_path, "JPEG")
            final_url = f"https://{host}/results/{wm_filename}"
        except Exception as e:
            print("Watermark error:", e)
            final_url = output_url

        # === Сохраняем контакт в CSV ===
        try:
            with open(CLIENTS_CSV, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([contact, dress, final_url])
        except Exception as e:
            print("CSV save error:", e)

        # === Отправка админу в Telegram ===
        if TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID:
            try:
                caption = f"Примерка ({dress}). Контакт: {contact}"
                tg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
                img = requests.get(final_url, timeout=60).content
                requests.post(
                    tg_url,
                    data={"chat_id": TELEGRAM_ADMIN_CHAT_ID, "caption": caption},
                    files={"photo": img},
                    timeout=60
                )
            except Exception as e:
                print("Telegram send error:", e)

        return jsonify({"output_url": final_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)


