from flask import Flask, request, jsonify
import asyncio
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import binascii
import aiohttp
import requests
import json
import like_pb2
import uid_generator_pb2
import visit_count_pb2
from google.protobuf.message import DecodeError
from collections import OrderedDict

# --- FIREBASE IMPORTS ---
import firebase_admin
from firebase_admin import credentials, firestore
import os

app = Flask(__name__)

# ==================== FIREBASE CONFIG ====================
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate("firebase_config.json")
        firebase_admin.initialize_app(cred)
    except Exception as e:
        app.logger.error(f"Firebase Init Error on Vercel: {e}")

db = firestore.client() if firebase_admin._apps else None


@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "ok", "service": "LIKE API", "endpoints": ["/like", "/remain"]})

VALID_API_KEYS = {
    "SUJEET"
}

daily_limit = 20
used_count = 0


def load_tokens(region):
    """
    Tải danh sách token trực tiếp từ file token_vn.json hoặc các file local theo region
    """
    try:
        region_upper = region.upper()
        tokens = []
        
        # 1. Nếu là region VN, ưu tiên đọc trực tiếp từ file token_vn.json hoặc accounts-VN.json
        if region_upper == "VN":
            file_paths = ["token_vn.json", os.path.join("DATA_ACCOUNTS", "ACCOUNTS", "accounts-VN.json")]
            for path in file_paths:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for item in data:
                            # Hỗ trợ linh hoạt cả key 'token' lẫn 'jwt_token'
                            t = item.get("token") or item.get("jwt_token")
                            if t:
                                tokens.append({"token": t})
                    if tokens:
                        app.logger.info(f"Đã tải {len(tokens)} token từ file local cho region VN")
                        return tokens

        # 2. Nếu không có file local, kiểm tra lấy từ Firebase (nếu đã cấu hình)
        if db:
            docs = db.collection('ff_tokens').document(region_upper).collection('accounts').stream()
            for doc in docs:
                data = doc.to_dict()
                t = data.get('token') or data.get('jwt_token')
                if t:
                    tokens.append({"token": t})
            if tokens:
                return tokens

        # 3. Fallback đọc các file dự phòng cho các vùng khác
        if region_upper == "IND":
            fallback_path = "token_ind.json"
        elif region_upper in {"BR", "US", "SAC", "NA"}:
            fallback_path = "token_br.json"
        else:
            fallback_path = "token_bd.json"
            
        if os.path.exists(fallback_path):
            with open(fallback_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    t = item.get("token") or item.get("jwt_token")
                    if t:
                        tokens.append({"token": t})
                        
        return tokens if tokens else None

    except Exception as e:
        app.logger.error(f"Error loading tokens for region {region}: {e}")
        return None


def encrypt_message(plaintext):
    try:
        key = b'Yg&tc%DEuh6%Zc^8'
        iv = b'6oyZDr22E3ychjM%'
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode('utf-8')
    except Exception as e:
        app.logger.error(f"Error encrypting message: {e}")
        return None


def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating protobuf message: {e}")
        return None


async def send_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                return await response.text()
    except Exception as e:
        app.logger.error(f"Exception in send_request: {e}")
        return None


async def send_multiple_requests(uid, region, url):
    try:
        protobuf_message = create_protobuf_message(uid, region)
        if protobuf_message is None:
            return None
        encrypted_uid = encrypt_message(protobuf_message)
        if encrypted_uid is None:
            return None
        tokens = load_tokens(region)
        if tokens is None:
            return None
        tasks = []
        for i in range(min(100, len(tokens))):
            token = tokens[i % len(tokens)]["token"]
            tasks.append(send_request(encrypted_uid, token, url))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results
    except Exception as e:
        app.logger.error(f"Exception in send_multiple_requests: {e}")
        return None


def create_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        app.logger.error(f"Error creating uid protobuf: {e}")
        return None


def enc(uid):
    protobuf_data = create_protobuf(uid)
    if protobuf_data is None:
        return None
    return encrypt_message(protobuf_data)


def make_request(encrypt, region, token):
    try:
        if region == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif region in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"
        edata = bytes.fromhex(encrypt)
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55"
        }
        response = requests.post(url, data=edata, headers=headers, verify=False)
        binary = response.content
        decoded = visit_count_pb2.Info()
        decoded.ParseFromString(binary)
        return decoded
    except DecodeError as e:
        app.logger.error(f"DecodeError: {e}")
        return None
    except Exception as e:
        app.logger.error(f"Error in make_request: {e}")
        return None


@app.route('/like', methods=['GET'])
def handle_requests():
    global used_count

    api_key = request.args.get("key")
    if api_key not in VALID_API_KEYS:
        result = OrderedDict([
            ("error", "Invalid or missing API key"),
            ("status", 3)
        ])
        return app.response_class(
            response=json.dumps(result, separators=(',', ':')),
            status=401,
            mimetype='application/json'
        )

    uid = request.args.get("uid")
    region = request.args.get("region", "").upper()
    if not uid or not region:
        return {"error": "UID and region are required"}, 400

    try:
        def process_request():
            global used_count

            tokens = load_tokens(region)
            if not tokens:
                raise Exception("Failed to load tokens.")
            token = tokens[0]['token']
            encrypted_uid = enc(uid)
            if encrypted_uid is None:
                raise Exception("Encryption of UID failed.")
            before = make_request(encrypted_uid, region, token)
            if before is None:
                raise Exception("Failed to get initial info.")
            before_like = before.AccountInfo.Likes

            if region == "IND":
                url = "https://client.ind.freefiremobile.com/LikeProfile"
            elif region in {"BR", "US", "SAC", "NA"}:
                url = "https://client.us.freefiremobile.com/LikeProfile"
            else:
                url = "https://clientbp.ggpolarbear.com/LikeProfile"

            asyncio.run(send_multiple_requests(uid, region, url))

            after = make_request(encrypted_uid, region, token)
            if after is None:
                raise Exception("Failed to get final info.")
            after_like = after.AccountInfo.Likes
            like_given = after_like - before_like
            status = 1 if like_given > 0 else 2

            if status == 1:
                used_count += 1

            remaining = max(daily_limit - used_count, 0)

            result = OrderedDict([
                ("LikesGivenByAPI", like_given),
                ("LikesafterCommand", after_like),
                ("LikesbeforeCommand", before_like),
                ("PlayerNickname", after.AccountInfo.PlayerNickname),
                ("Level", after.AccountInfo.Levels),
                ("Region", after.AccountInfo.PlayerRegion),
                ("UID", after.AccountInfo.UID),
                ("status", status),
                ("daily_limit", daily_limit),
                ("used", used_count),
                ("remaining", remaining)
            ])

            return app.response_class(
                response=json.dumps(result, separators=(',', ':')),
                status=200,
                mimetype='application/json'
            )

        return process_request()

    except Exception as e:
        app.logger.error(f"Error: {e}")
        return {"error": str(e)}, 500


@app.route('/remain', methods=['GET'])
def remain_info():
    global used_count
    remaining = max(daily_limit - used_count, 0)
    data = {
        "daily_limit": daily_limit,
        "remaining": remaining,
        "used": used_count,
        "reset_info": "4:00 AM IST"
    }
    return jsonify(data)


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
