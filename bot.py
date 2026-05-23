import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import json
import time
import threading
import os
import uuid
import html
import re
import pyotp
import random
import copy
from datetime import datetime

# ============================================
# --- STYLE & BULLETPROOF COPY BUTTON PATCH ---
# ============================================
_old_inline_dict = InlineKeyboardButton.to_dict
def _new_inline_dict(self):
    d = _old_inline_dict(self)
    if hasattr(self, 'style'): 
        d['style'] = self.style
        
    if hasattr(self, 'custom_copy_text') and self.custom_copy_text:
        d['copy_text'] = {'text': str(self.custom_copy_text)}
        if 'callback_data' in d:
            del d['callback_data']
            
    return d
InlineKeyboardButton.to_dict = _new_inline_dict

_old_kb_dict = KeyboardButton.to_dict
def _new_kb_dict(self):
    d = _old_kb_dict(self)
    if hasattr(self, 'style'): d['style'] = self.style
    return d
KeyboardButton.to_dict = _new_kb_dict

# Helper functions to easily create colorful buttons
def ibtn(text, callback_data=None, url=None, style=None, copy_text_str=None):
    kwargs = {'text': text}
    
    if copy_text_str:
        kwargs['callback_data'] = "fake_copy_btn"
    else:
        if callback_data: kwargs['callback_data'] = callback_data
        if url: kwargs['url'] = url
            
    b = InlineKeyboardButton(**kwargs)
    if style: b.style = style
    
    if copy_text_str:
        b.custom_copy_text = copy_text_str
        
    return b

def rbtn(text, style=None):
    b = KeyboardButton(text=text)
    if style: b.style = style
    return b
# ============================================


# --- CONFIGURATION ---
TOKEN = "8194162003:AAFArsa7IIyjGPYselHX7OvGYi83nnXIkwc"
ADMIN_ID = 7095358778


bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=50)


req_session = requests.Session()
retries = Retry(total=5, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(pool_connections=1000, pool_maxsize=1000, max_retries=retries)
req_session.mount('http://', adapter)
req_session.mount('https://', adapter)
DATA_FILE = "dxa_bot_premium_data_v4.json"
DEFAULT_APPS = []

active_polls = {}
user_states = {}
data_lock = threading.RLock()
menu_message_id = {}
two_fa_message_id = {}
login_sessions = {}  # Store login sessions per panel
user_cooldowns = {}  # Track cooldowns per user {user_id: last_request_time}

# ============ MULTI-PANEL API FORMATS ============
PANEL_FORMATS = {
    "nexaotp": {
        "label": "NexaOTP (nxa_ key)",
        "get_number": "/api/v1/numbers/get",
        "get_sms": "/api/v1/numbers/{number_id}/sms",
        "http_method": "POST",
        "auth_header": "X-API-Key",
        "post_body": {"range": "{service}"},
        "number_field": "number",
        "otp_field": "otp",
        "sms_field": "sms",
        "success_field": "success",
        "id_field": "number_id"
    },
    "ins_agent": {
        "label": "INS Agent API (sk_ key)",
        "get_number": "/api/functions/agent-api/numbers?status=assigned&limit={limit}&cli={service}",
        "get_sms": "/api/functions/agent-api/otp?number={number_id}&limit=5",
        "get_stats": "/api/functions/agent-api/stats",
        "get_cli_ranges": "/api/functions/agent-api/cli-ranges",
        "http_method": "GET",
        "auth_header": "x-api-key",
        "number_field": "number",
        "otp_field": "otp_code",
        "sms_field": "message_text",
        "success_field": "ok",
        "id_field": "id",
        "data_wrapper": "data"
    },
    "standard": {
        "label": "Standard API",
        "get_number": "/getNumber?service={service}&country={country}",
        "get_sms": "/numbers/{number_id}/sms",
        "http_method": "GET",
        "auth_header": "X-API-Key",
        "number_field": "number",
        "otp_field": "otp",
        "sms_field": "sms",
        "success_field": "success",
        "id_field": "id"
    },
    "daisysms": {
        "label": "DaisySMS / 5sim Type",
        "get_number": "/stubs/handler_api.php?api_key={api_key}&action=getNumber&service={service}&country={country}",
        "get_sms": "/stubs/handler_api.php?api_key={api_key}&action=getStatus&id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "number_field": "phone",
        "otp_field": "code",
        "sms_field": "full_sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id"
    },
    "smshub": {
        "label": "SMSHub Type",
        "get_number": "/api/getNumber?api_key={api_key}&service={service}&country={country}",
        "get_sms": "/api/getStatus?api_key={api_key}&id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "response",
        "success_value": "1",
        "id_field": "id"
    },
    "grizzlysms": {
        "label": "GrizzlySMS / Tiger Type",
        "get_number": "/api/get-number?apikey={api_key}&service={service}&country={country}",
        "get_sms": "/api/get-sms?apikey={api_key}&id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "number_field": "number",
        "otp_field": "otp",
        "sms_field": "message",
        "success_field": "success",
        "id_field": "request_id"
    },
    "custom": {
        "label": "Custom / Manual URL",
        "get_number": "",
        "get_sms": "",
        "http_method": "GET",
        "auth_header": "X-API-Key",
        "number_field": "number",
        "otp_field": "otp",
        "sms_field": "sms",
        "success_field": "success",
        "id_field": "id"
    },
    "ints": {
        "label": "INTS Panel (Login Based)",
        "login_endpoint": "/signin",
        "get_number": "/api/getNumber?service={service}&country={country}",
        "get_sms": "/api/getStatus?id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "session",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id",
        "has_captcha": True,
        "captcha_type": "math"
    },
    "ints_v2": {
        "label": "INTS v2 (signmein)",
        "login_endpoint": "/signmein",
        "get_number": "/api/getNumber?service={service}&country={country}",
        "get_sms": "/api/getStatus?id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "session",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id",
        "has_captcha": True,
        "captcha_type": "math"
    },
    "numberpanel": {
        "label": "Number Panel",
        "login_endpoint": "/signin",
        "get_number": "/api/getNumber?service={service}&country={country}",
        "get_sms": "/api/getStatus?id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "session",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id",
        "has_captcha": True,
        "captcha_type": "math"
    },
    "sms_panel": {
        "label": "SMS Panel (/sms type)",
        "login_endpoint": "/signmein",
        "get_number": "/api/getNumber?service={service}&country={country}",
        "get_sms": "/api/getStatus?id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "session",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id",
        "has_captcha": True,
        "captcha_type": "math"
    },
    "konekta": {
        "label": "Konekta Premium",
        "login_endpoint": "/login",
        "get_number": "/api/getNumber?service={service}&country={country}",
        "get_sms": "/api/getStatus?id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "session",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id"
    },
    "timesms": {
        "label": "Time SMS",
        "login_endpoint": "/signin",
        "get_number": "/api/getNumber?service={service}&country={country}",
        "get_sms": "/api/getStatus?id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "session",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id",
        "has_captcha": True,
        "captcha_type": "math"
    },
    "grand_panel": {
        "label": "Grand Panel",
        "login_endpoint": "/signin",
        "get_number": "/api/getNumber?service={service}&country={country}",
        "get_sms": "/api/getStatus?id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "session",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id"
    },
    "pscall": {
        "label": "PSCall Panel",
        "login_endpoint": "/signin",
        "get_number": "/api/getNumber?service={service}&country={country}",
        "get_sms": "/api/getStatus?id={number_id}",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "session",
        "number_field": "number",
        "otp_field": "code",
        "sms_field": "sms",
        "success_field": "status",
        "success_value": "OK",
        "id_field": "id"
    },
    "lamix": {
        "label": "Lamix CRAPI (Token)",
        "get_number": "",
        "get_sms": "/viewstats?token={api_key}&num={number_id}&dt1={dt1}&dt2={dt2}&records=10",
        "http_method": "GET",
        "auth_header": "",
        "auth_type": "token_url",
        "number_field": "num",
        "otp_field": "otp",
        "sms_field": "message",
        "success_field": "status",
        "success_value": "success",
        "id_field": "num",
        "data_wrapper": "data"
    }
}



def _get_api_base(api_url, fmt_name=""):
    """Get API base URL, stripping dashboard/UI paths that break API endpoints."""
    from urllib.parse import urlparse
    url = api_url.rstrip("/")
    if not url:
        return url
    if fmt_name == "ins_agent":
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    if fmt_name == "lamix":
        idx = url.lower().find("/crapi/lamix")
        if idx != -1:
            return url[:idx + 12]
        idx = url.lower().find("/crapi")
        if idx != -1:
            return url[:idx + 6]
        return url
    if fmt_name in ("ints", "ints_v2"):
        idx = url.lower().find("/ints")
        if idx != -1:
            return url[:idx + 5]
    if fmt_name == "numberpanel":
        idx = url.lower().find("/numberpanel")
        if idx != -1:
            return url[:idx + 12]
    if fmt_name == "sms_panel":
        idx = url.lower().find("/sms")
        if idx != -1:
            return url[:idx + 4]
    for suffix in ["/dashboard", "/admin", "/panel", "/home", "/app", "/login", "/signin"]:
        if url.lower().endswith(suffix):
            url = url[:len(url) - len(suffix)]
            break
    return url

def detect_panel_format(api_url, api_key=""):
    url = api_url.lower().rstrip("/")
    if "handler_api" in url or "stubs" in url or "5sim" in url or "daisysms" in url:
        return "daisysms"
    if "smshub" in url or "sms-hub" in url:
        return "smshub"
    if "grizzly" in url or "tiger" in url or "bear" in url:
        return "grizzlysms"
    if api_key.startswith("nxa_"):
        return "nexaotp"
    if api_key.startswith("sk_"):
        return "ins_agent"
    # Detect ints-type panels from URL
    if url.endswith("/ints") or "/ints/" in url or "/ints?" in url:
        return "ints"
    # Detect NumberPanel
    if "numberpanel" in url.lower():
        return "numberpanel"
    # Detect /sms type panels (Purple Numbers, Xisora)
    if url.endswith("/sms") or "/sms/" in url:
        return "sms_panel"
    # Detect known panel domains
    if "konektapremium" in url or "konekta" in url:
        return "konekta"
    if "timesms" in url:
        return "timesms"
    if "grand-panel" in url or "grandpanel" in url:
        return "grand_panel"
    if "pscall" in url:
        return "pscall"
    if "imssms" in url:
        return "ints"
    if "crapi/lamix" in url or "crapi" in url:
        return "lamix"
    return "standard"

def build_api_url(panel, endpoint_type, **kwargs):
    api_url = panel.get("api_url", "").rstrip("/")
    api_key = panel.get("api_key", "")
    fmt_name = panel.get("api_format", detect_panel_format(api_url, api_key))
    fmt = PANEL_FORMATS.get(fmt_name, PANEL_FORMATS["standard"])
    
    custom_endpoints = panel.get("custom_endpoints", {})
    if endpoint_type in custom_endpoints and custom_endpoints[endpoint_type]:
        template = custom_endpoints[endpoint_type]
    else:
        template = fmt.get(endpoint_type, "")
    
    if not template:
        return None
    
    safe_kwargs = {"api_key": api_key, "service": kwargs.get("service", ""), "country": kwargs.get("country", ""), "number_id": kwargs.get("number_id", ""), "limit": kwargs.get("limit", "10")}
    safe_kwargs.update({k: v for k, v in kwargs.items() if k not in safe_kwargs})
    try:
        url = template.format(**safe_kwargs)
    except (KeyError, IndexError):
        url = template
    
    if url.startswith("http"):
        return url
    base = _get_api_base(api_url, fmt_name)
    return f"{base}{url}"

def get_panel_http_method(panel):
    api_key = panel.get("api_key", "")
    fmt_name = panel.get("api_format", detect_panel_format(panel.get("api_url", ""), api_key))
    fmt = PANEL_FORMATS.get(fmt_name, PANEL_FORMATS["standard"])
    return fmt.get("http_method", "GET").upper()

def get_api_headers(panel):
    api_key = panel.get("api_key", "")
    fmt_name = panel.get("api_format", detect_panel_format(panel.get("api_url", ""), api_key))
    fmt = PANEL_FORMATS.get(fmt_name, PANEL_FORMATS["standard"])
    auth_header = fmt.get("auth_header", "X-API-Key")
    if auth_header:
        return {auth_header: api_key}
    return {}

def parse_number_response(panel, res_data):
    api_key = panel.get("api_key", "")
    fmt_name = panel.get("api_format", detect_panel_format(panel.get("api_url", ""), api_key))
    fmt = PANEL_FORMATS.get(fmt_name, PANEL_FORMATS["standard"])
    
    success_field = fmt.get("success_field", "success")
    success_value = fmt.get("success_value", None)
    
    is_success = False
    if success_value:
        is_success = str(res_data.get(success_field, "")) == str(success_value)
    else:
        is_success = bool(res_data.get(success_field, False))
    
    if not is_success:
        for k in ["success", "status", "response", "ok", "result"]:
            v = res_data.get(k)
            if v is True or v == 1 or v == "1" or v == "OK" or v == "ok" or v == "SUCCESS":
                is_success = True
                break
    
    number = None
    for field in [fmt.get("number_field", "number"), "number", "phone", "phoneNumber", "tel"]:
        if res_data.get(field):
            number = str(res_data[field])
            break
    
    num_id = None
    for field in [fmt.get("id_field", "id"), "id", "request_id", "order_id", "activation_id"]:
        if res_data.get(field):
            num_id = str(res_data[field])
            break
    
    return {"success": is_success, "number": number, "id": num_id}

def parse_sms_response(panel, res_data):
    api_key = panel.get("api_key", "")
    fmt_name = panel.get("api_format", detect_panel_format(panel.get("api_url", ""), api_key))
    fmt = PANEL_FORMATS.get(fmt_name, PANEL_FORMATS["standard"])
    
    success_field = fmt.get("success_field", "success")
    success_value = fmt.get("success_value", None)
    
    is_success = False
    if success_value:
        is_success = str(res_data.get(success_field, "")) == str(success_value)
    else:
        is_success = bool(res_data.get(success_field, False))
    
    if not is_success:
        for k in ["success", "status", "response", "ok", "result"]:
            v = res_data.get(k)
            if v is True or v == 1 or v == "1" or v == "OK" or v == "ok" or v == "SUCCESS":
                is_success = True
                break
    
    otp = None
    for field in [fmt.get("otp_field", "otp"), "otp", "code", "sms_code", "verification_code"]:
        if res_data.get(field):
            otp = str(res_data[field])
            break
    
    sms = ""
    for field in [fmt.get("sms_field", "sms"), "sms", "message", "full_sms", "text", "msg"]:
        if res_data.get(field):
            sms = str(res_data[field])
            break
    
    service = ""
    for field in ["service", "app_name", "app", "serviceName", "platform"]:
        if res_data.get(field):
            service = str(res_data[field])
            break
    
    return {"success": is_success, "otp": otp, "sms": sms, "service": service}


# ============================================

# --- ENHANCED LANGUAGE DETECTION ---
def detect_language(text):
    if not text: return "EN"
    text_str = str(text)
    
    if any('\u0600' <= c <= '\u06ff' for c in text_str):
        if any(w in text_str.lower() for w in ["كود", "رمز", "تحقق", "التحقق", "تأكيد", "واتساب"]): return "AR"
        if any(w in text_str.lower() for w in ["کوڈ", "رمز", "تصدیق", "واٹس"]): return "UR"
        if any(w in text_str.lower() for w in ["کد", "رمز", "تأیید", "واتس"]): return "FA"
        if any(w in text_str.lower() for w in ["پاسه", "رمز", "کوډ"]): return "PS"
        return "AR"
    
    if any('\u0980' <= c <= '\u09ff' for c in text_str): return "BN"
    if any('\u0900' <= c <= '\u097f' for c in text_str): return "HI"
    if any('\u0b80' <= c <= '\u0bff' for c in text_str): return "TA"
    if any('\u0c00' <= c <= '\u0c7f' for c in text_str): return "TE"
    if any('\u0c80' <= c <= '\u0cff' for c in text_str): return "KN"
    if any('\u0d00' <= c <= '\u0d7f' for c in text_str): return "ML"
    if any('\u0d80' <= c <= '\u0dff' for c in text_str): return "SI"
    
    if any('\u1000' <= c <= '\u109f' for c in text_str): return "MY"
    if any('\u1780' <= c <= '\u17ff' for c in text_str): return "KM"
    if any('\u0e80' <= c <= '\u0eff' for c in text_str):
        if not any('\u0e00' <= c <= '\u0e7f' for c in text_str): return "LO"
    if any('\u0e00' <= c <= '\u0e7f' for c in text_str): return "TH"
    
    if any('\u4e00' <= c <= '\u9fff' for c in text_str): return "ZH"
    if any('\u3040' <= c <= '\u309f' for c in text_str): return "JA"
    if any('\u30a0' <= c <= '\u30ff' for c in text_str): return "JA"
    if any('\uac00' <= c <= '\ud7af' for c in text_str): return "KO"
    if any('\u1100' <= c <= '\u11ff' for c in text_str): return "KO"
    
    if any('\u0400' <= c <= '\u04ff' for c in text_str): return "RU"
    if any('\u10a0' <= c <= '\u10ff' for c in text_str): return "KA"
    if any('\u0530' <= c <= '\u058f' for c in text_str): return "HY"
    if any('\u0370' <= c <= '\u03ff' for c in text_str): return "EL"
    if any('\u0590' <= c <= '\u05ff' for c in text_str): return "HE"
    if any('\u1200' <= c <= '\u137f' for c in text_str): return "AM"
    if any('\u0f00' <= c <= '\u0fff' for c in text_str): return "BO"
    
    if any(c in 'ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ' for c in text_str): return "VN"
    
    text_lower = text_str.lower()
    if any(w in text_lower for w in ["código", "contraseña", "verificación", "clave", "acceso"]): return "ES"
    if any(w in text_lower for w in ["code secret", "vérification", "mot de passe", "confirmation", "votre code"]): return "FR"
    if any(w in text_lower for w in ["código de", "senha de", "verificação", "chave", "acesso"]): return "PT"
    if any(w in text_lower for w in ["doğrulama", "şifre", "kod", "giriş", "onay", "parola"]): return "TR"
    if any(w in text_lower for w in ["kode verifikasi", "pengesahan", "kata laluan", "kod", "sahkan"]): return "ID"
    if any(w in text_lower for w in ["bestätigungscode", "sicherheitscode", "passwort", "zugangscode", "verifizierung"]): return "DE"
    if any(w in text_lower for w in ["codice di", "verifica", "password", "conferma", "accesso"]): return "IT"
    if any(w in text_lower for w in ["verificatiecode", "bevestigingscode", "toegangscode", "wachtwoord"]): return "NL"
    if any(w in text_lower for w in ["kod weryfikacyjny", "hasło", "potwierdzenie", "dostęp", "klucz"]): return "PL"
    if any(w in text_lower for w in ["cod de", "parola", "confirmare", "verificare", "acces"]): return "RO"
    if any(w in text_lower for w in ["ověřovací kód", "heslo", "přístup", "potvrzení"]): return "CS"
    if any(w in text_lower for w in ["overovací kód", "heslo", "prístup", "potvrdenie"]): return "SK"
    if any(w in text_lower for w in ["megerősítő kód", "jelszó", "hozzáférés", "ellenőrzés"]): return "HU"
    if any(w in text_lower for w in ["verifieringskod", "lösenord", "bekräftelse", "åtkomst"]): return "SV"
    if any(w in text_lower for w in ["verifiseringskode", "passord", "bekreftelse", "tilgang"]): return "NO"
    if any(w in text_lower for w in ["bekræftelseskode", "adgangskode", "verifikation", "bekræft"]): return "DA"
    if any(w in text_lower for w in ["vahvistuskoodi", "salasana", "tunnus", "varmennus"]): return "FI"
    if any(w in text_lower for w in ["potvrdni kod", "lozinka", "pristup", "verifikacija"]): return "HR"
    if any(w in text_lower for w in ["potrditvena koda", "geslo", "dostop", "preverjanje"]): return "SL"
    if any(w in text_lower for w in ["patvirtinimo kodas", "slaptažodis", "prieiga", "patikrinimas"]): return "LT"
    if any(w in text_lower for w in ["apstiprinājuma kods", "parole", "piekļuve", "verifikācija"]): return "LV"
    if any(w in text_lower for w in ["kinnituskood", "parool", "juurdepääs", "kontroll"]): return "ET"
    if any(w in text_lower for w in ["code ng", "password", "pagpapatunay", "access", "kumpirmasyon"]): return "TL"
    
    return "EN"

# --- ENHANCED SERVICE DETECTION ---
SERVICE_SMS_KEYWORDS = {
    "whatsapp": ["whatsapp", "wa", "wap", "w/a", "whatsapp business", "whatsapp code", "whatsapp verification", "whatsapp kod"],
    "facebook": ["facebook", "fb", "meta", "fbook", "fb code", "facebook code", "fb confirmation"],
    "instagram": ["instagram", "insta", "ig", "ig code", "instagram code"],
    "telegram": ["telegram", "tg", "tele", "telegram code", "tg code"],
    "google": ["google", "gmail", "youtube", "g-", "google voice", "google verification"],
    "tiktok": ["tiktok", "tik tok", "tikvideo", "tiktok code", "tik code"],
    "snapchat": ["snapchat", "snap", "snap code", "snapchat code"],
    "twitter": ["twitter", "x.com", "x code", "your x confirmation", "twitter code"],
    "binance": ["binance", "bnb", "binances", "binance verification"],
    "melbet": ["melbet", "mel", "melbet code"],
    "bkash": ["bkash", "b-kash", "bkash code"],
    "nagad": ["nagad", "nagad code"],
    "imo": ["imo", "imo code", "imo verification"],
    "microsoft": ["microsoft", "ms", "outlook", "microsoft account", "ms code"],
    "apple": ["apple", "icloud", "itunes", "apple id", "apple code"],
    "paypal": ["paypal", "pay pal", "paypal code"],
    "uber": ["uber", "uber code", "uber verification"],
    "amazon": ["amazon", "amzn", "amazon code"],
    "netflix": ["netflix", "netflix code"],
    "discord": ["discord", "discord code"],
    "spotify": ["spotify", "spotify code"],
    "linkedin": ["linkedin", "linked in", "linkedin code"],
    "yahoo": ["yahoo", "yahoo code"],
    "viber": ["viber", "viber code"],
    "line": ["line", "line code", "line verification"],
    "wechat": ["wechat", "we chat", "wechat code"],
    "signal": ["signal", "signal code"],
}

def detect_service_from_sms(sms_text, app_name=""):
    if not sms_text and not app_name:
        return "Unknown"
    
    sms_lower = str(sms_text).lower() if sms_text else ""
    app_lower = str(app_name).lower() if app_name else ""
    
    if any(w in sms_lower for w in ["whatsapp", "wa ", " w/a", "whatsapp code", "whatsapp kod", "whatsapp verification"]):
        return "Whatsapp"
    
    for service, keywords in SERVICE_SMS_KEYWORDS.items():
        for kw in keywords:
            if kw in sms_lower:
                return service.title()
    
    if app_lower and app_lower != "custom search":
        for service, keywords in SERVICE_SMS_KEYWORDS.items():
            for kw in keywords:
                if kw in app_lower or app_lower in service:
                    return service.title()
        return app_name.title()
    
    return "Unknown"

# --- ALL 240+ COUNTRY FLAGS ---
COUNTRY_FLAGS = {
    "afghanistan": "🇦🇫", "albania": "🇦🇱", "algeria": "🇩🇿", "andorra": "🇦🇩", "angola": "🇦🇴",
    "antigua and barbuda": "🇦🇬", "argentina": "🇦🇷", "armenia": "🇦🇲", "australia": "🇦🇺",
    "austria": "🇦🇹", "azerbaijan": "🇦🇿", "bahamas": "🇧🇸", "bahrain": "🇧🇭",
    "bangladesh": "🇧🇩", "barbados": "🇧🇧", "belarus": "🇧🇾", "belgium": "🇧🇪", "belize": "🇧🇿",
    "benin": "🇧🇯", "bhutan": "🇧🇹", "bolivia": "🇧🇴", "bosnia and herzegovina": "🇧🇦",
    "botswana": "🇧🇼", "brazil": "🇧🇷", "brunei": "🇧🇳", "bulgaria": "🇧🇬",
    "burkina faso": "🇧🇫", "burundi": "🇧🇮", "cambodia": "🇰🇭", "cameroon": "🇨🇲",
    "canada": "🇨🇦", "cape verde": "🇨🇻", "central african republic": "🇨🇫", "chad": "🇹🇩",
    "chile": "🇨🇱", "china": "🇨🇳", "colombia": "🇨🇴", "comoros": "🇰🇲", "congo": "🇨🇬",
    "costa rica": "🇨🇷", "cote d'ivoire": "🇨🇮", "ivory coast": "🇨🇮",
    "croatia": "🇭🇷", "cuba": "🇨🇺", "cyprus": "🇨🇾", "czech republic": "🇨🇿",
    "denmark": "🇩🇰", "djibouti": "🇩🇯", "dominica": "🇩🇲", "dominican republic": "🇩🇴",
    "drc": "🇨🇩", "ecuador": "🇪🇨", "egypt": "🇪🇬", "el salvador": "🇸🇻",
    "equatorial guinea": "🇬🇶", "eritrea": "🇪🇷", "estonia": "🇪🇪", "eswatini": "🇸🇿",
    "ethiopia": "🇪🇹", "fiji": "🇫🇯", "finland": "🇫🇮", "france": "🇫🇷",
    "gabon": "🇬🇦", "gambia": "🇬🇲", "georgia": "🇬🇪", "germany": "🇩🇪", "ghana": "🇬🇭",
    "greece": "🇬🇷", "grenada": "🇬🇩", "guatemala": "🇬🇹", "guinea": "🇬🇳",
    "guinea bissau": "🇬🇼", "guyana": "🇬🇾", "haiti": "🇭🇹", "honduras": "🇭🇳",
    "hong kong": "🇭🇰", "hungary": "🇭🇺", "iceland": "🇮🇸", "india": "🇮🇳",
    "indonesia": "🇮🇩", "iran": "🇮🇷", "iraq": "🇮🇶", "ireland": "🇮🇪", "israel": "🇮🇱",
    "italy": "🇮🇹", "jamaica": "🇯🇲", "japan": "🇯🇵", "jordan": "🇯🇴", "kazakhstan": "🇰🇿",
    "kenya": "🇰🇪", "kiribati": "🇰🇮", "kosovo": "🇽🇰", "kuwait": "🇰🇼", "kyrgyzstan": "🇰🇬",
    "laos": "🇱🇦", "latvia": "🇱🇻", "lebanon": "🇱🇧", "lesotho": "🇱🇸", "liberia": "🇱🇷",
    "libya": "🇱🇾", "liechtenstein": "🇱🇮", "lithuania": "🇱🇹", "luxembourg": "🇱🇺",
    "macau": "🇲🇴", "madagascar": "🇲🇬", "malawi": "🇲🇼", "malaysia": "🇲🇾", "maldives": "🇲🇻",
    "mali": "🇲🇱", "malta": "🇲🇹", "marshall islands": "🇲🇭", "mauritania": "🇲🇷",
    "mauritius": "🇲🇺", "mexico": "🇲🇽", "micronesia": "🇫🇲", "moldova": "🇲🇩",
    "monaco": "🇲🇨", "mongolia": "🇲🇳", "montenegro": "🇲🇪", "morocco": "🇲🇦",
    "mozambique": "🇲🇿", "myanmar": "🇲🇲", "namibia": "🇳🇦", "nauru": "🇳🇷", "nepal": "🇳🇵",
    "netherlands": "🇳🇱", "new zealand": "🇳🇿", "nicaragua": "🇳🇮", "niger": "🇳🇪",
    "nigeria": "🇳🇬", "north korea": "🇰🇵", "north macedonia": "🇲🇰", "norway": "🇳🇴",
    "oman": "🇴🇲", "pakistan": "🇵🇰", "palau": "🇵🇼", "palestine": "🇵🇸", "panama": "🇵🇦",
    "papua new guinea": "🇵🇬", "paraguay": "🇵🇾", "peru": "🇵🇪", "philippines": "🇵🇭",
    "poland": "🇵🇱", "portugal": "🇵🇹", "qatar": "🇶🇦", "romania": "🇷🇴", "russia": "🇷🇺",
    "rwanda": "🇷🇼", "saint kitts and nevis": "🇰🇳", "saint lucia": "🇱🇨",
    "saint vincent and the grenadines": "🇻🇨", "samoa": "🇼🇸", "san marino": "🇸🇲",
    "sao tome and principe": "🇸🇹", "saudi arabia": "🇸🇦", "senegal": "🇸🇳", "serbia": "🇷🇸",
    "seychelles": "🇸🇨", "sierra leone": "🇸🇱", "singapore": "🇸🇬", "slovakia": "🇸🇰",
    "slovenia": "🇸🇮", "solomon islands": "🇸🇧", "somalia": "🇸🇴", "south africa": "🇿🇦",
    "south korea": "🇰🇷", "south sudan": "🇸🇸", "spain": "🇪🇸", "sri lanka": "🇱🇰",
    "sudan": "🇸🇩", "suriname": "🇸🇷", "sweden": "🇸🇪", "switzerland": "🇨🇭", "syria": "🇸🇾",
    "taiwan": "🇹🇼", "tajikistan": "🇹🇯", "tanzania": "🇹🇿", "thailand": "🇹🇭",
    "timor leste": "🇹🇱", "togo": "🇹🇬", "tonga": "🇹🇴", "trinidad and tobago": "🇹🇹",
    "tunisia": "🇹🇳", "turkey": "🇹🇷", "turkmenistan": "🇹🇲", "tuvalu": "🇹🇻",
    "uganda": "🇺🇬", "ukraine": "🇺🇦", "uae": "🇦🇪", "united arab emirates": "🇦🇪",
    "united kingdom": "🇬🇧", "uk": "🇬🇧", "usa": "🇺🇸", "united states": "🇺🇸",
    "uruguay": "🇺🇾", "uzbekistan": "🇺🇿", "vanuatu": "🇻🇺", "vatican city": "🇻🇦",
    "venezuela": "🇻🇪", "vietnam": "🇻🇳", "yemen": "🇾🇪", "zambia": "🇿🇲", "zimbabwe": "🇿🇼",
    "anguilla": "🇦🇮", "aruba": "🇦🇼", "bermuda": "🇧🇲", "british virgin islands": "🇻🇬",
    "cayman islands": "🇰🇾", "curacao": "🇨🇼", "falkland islands": "🇫🇰",
    "french guiana": "🇬🇫", "greenland": "🇬🇱", "guadeloupe": "🇬🇵",
    "guam": "🇬🇺", "martinique": "🇲🇶", "mayotte": "🇾🇹", "montserrat": "🇲🇸",
    "new caledonia": "🇳🇨", "niue": "🇳🇺", "norfolk island": "🇳🇫",
    "northern mariana islands": "🇲🇵", "pitcairn islands": "🇵🇳", "puerto rico": "🇵🇷",
    "reunion": "🇷🇪", "saint helena": "🇸🇭", "tokelau": "🇹🇰",
    "turks and caicos islands": "🇹🇨", "us virgin islands": "🇻🇮",
    "wallis and futuna": "🇼🇫", "western sahara": "🇪🇭", "cook islands": "🇨🇰",
    "french polynesia": "🇵🇫", "gibraltar": "🇬🇮", "faroe islands": "🇫🇴",
    "svalbard and jan mayen": "🇸🇯", "aland islands": "🇦🇽", "jersey": "🇯🇪",
    "guernsey": "🇬🇬", "isle of man": "🇮🇲", "saint pierre and miquelon": "🇵🇲",
    "sint maarten": "🇸🇽", "bonaire": "🇧🇶"
}

COUNTRY_ISO = {
    "afghanistan": "AF", "albania": "AL", "algeria": "DZ", "andorra": "AD", "angola": "AO",
    "antigua and barbuda": "AG", "argentina": "AR", "armenia": "AM", "australia": "AU",
    "austria": "AT", "azerbaijan": "AZ", "bahamas": "BS", "bahrain": "BH", "bangladesh": "BD",
    "barbados": "BB", "belarus": "BY", "belgium": "BE", "belize": "BZ", "benin": "BJ",
    "bhutan": "BT", "bolivia": "BO", "bosnia and herzegovina": "BA", "botswana": "BW",
    "brazil": "BR", "brunei": "BN", "bulgaria": "BG", "burkina faso": "BF", "burundi": "BI",
    "cambodia": "KH", "cameroon": "CM", "canada": "CA", "cape verde": "CV",
    "central african republic": "CF", "chad": "TD", "chile": "CL", "china": "CN",
    "colombia": "CO", "comoros": "KM", "congo": "CG", "costa rica": "CR", "cote d'ivoire": "CI",
    "ivory coast": "CI", "croatia": "HR", "cuba": "CU", "cyprus": "CY", "czech republic": "CZ",
    "denmark": "DK", "djibouti": "DJ", "dominica": "DM", "dominican republic": "DO",
    "drc": "CD", "ecuador": "EC", "egypt": "EG", "el salvador": "SV", "equatorial guinea": "GQ",
    "eritrea": "ER", "estonia": "EE", "eswatini": "SZ", "ethiopia": "ET", "fiji": "FJ",
    "finland": "FI", "france": "FR", "gabon": "GA", "gambia": "GM", "georgia": "GE",
    "germany": "DE", "ghana": "GH", "greece": "GR", "grenada": "GD", "guatemala": "GT",
    "guinea": "GN", "guinea bissau": "GW", "guyana": "GY", "haiti": "HT", "honduras": "HN",
    "hong kong": "HK", "hungary": "HU", "iceland": "IS", "india": "IN", "indonesia": "ID",
    "iran": "IR", "iraq": "IQ", "ireland": "IE", "israel": "IL", "italy": "IT",
    "jamaica": "JM", "japan": "JP", "jordan": "JO", "kazakhstan": "KZ", "kenya": "KE",
    "kiribati": "KI", "kosovo": "XK", "kuwait": "KW", "kyrgyzstan": "KG", "laos": "LA",
    "latvia": "LV", "lebanon": "LB", "lesotho": "LS", "liberia": "LR", "libya": "LY",
    "liechtenstein": "LI", "lithuania": "LT", "luxembourg": "LU", "macau": "MO",
    "madagascar": "MG", "malawi": "MW", "malaysia": "MY", "maldives": "MV", "mali": "ML",
    "malta": "MT", "marshall islands": "MH", "mauritania": "MR", "mauritius": "MU",
    "mexico": "MX", "micronesia": "FM", "moldova": "MD", "monaco": "MC", "mongolia": "MN",
    "montenegro": "ME", "morocco": "MA", "mozambique": "MZ", "myanmar": "MM", "namibia": "NA",
    "nauru": "NR", "nepal": "NP", "netherlands": "NL", "new zealand": "NZ", "nicaragua": "NI",
    "niger": "NE", "nigeria": "NG", "north korea": "KP", "north macedonia": "MK", "norway": "NO",
    "oman": "OM", "pakistan": "PK", "palau": "PW", "palestine": "PS", "panama": "PA",
    "papua new guinea": "PG", "paraguay": "PY", "peru": "PE", "philippines": "PH", "poland": "PL",
    "portugal": "PT", "qatar": "QA", "romania": "RO", "russia": "RU", "rwanda": "RW",
    "saint kitts and nevis": "KN", "saint lucia": "LC", "saint vincent and the grenadines": "VC",
    "samoa": "WS", "san marino": "SM", "sao tome and principe": "ST", "saudi arabia": "SA",
    "senegal": "SN", "serbia": "RS", "seychelles": "SC", "sierra leone": "SL", "singapore": "SG",
    "slovakia": "SK", "slovenia": "SI", "solomon islands": "SB", "somalia": "SO",
    "south africa": "ZA", "south korea": "KR", "south sudan": "SS", "spain": "ES",
    "sri lanka": "LK", "sudan": "SD", "suriname": "SR", "sweden": "SE", "switzerland": "CH",
    "syria": "SY", "taiwan": "TW", "tajikistan": "TJ", "tanzania": "TZ", "thailand": "TH",
    "timor leste": "TL", "togo": "TG", "tonga": "TO", "trinidad and tobago": "TT",
    "tunisia": "TN", "turkey": "TR", "turkmenistan": "TM", "tuvalu": "TV", "uganda": "UG",
    "ukraine": "UA", "uae": "AE", "united arab emirates": "AE", "united kingdom": "GB", "uk": "GB",
    "usa": "US", "united states": "US", "uruguay": "UY", "uzbekistan": "UZ", "vanuatu": "VU",
    "vatican city": "VA", "venezuela": "VE", "vietnam": "VN", "yemen": "YE", "zambia": "ZM", "zimbabwe": "ZW",
    "anguilla": "AI", "aruba": "AW", "bermuda": "BM", "cayman islands": "KY", "curacao": "CW",
    "greenland": "GL", "guam": "GU", "puerto rico": "PR", "reunion": "RE", "western sahara": "EH"
}

PHONE_TO_COUNTRY = {
    "1": "United States", "7": "Russia", "20": "Egypt", "27": "South Africa",
    "30": "Greece", "31": "Netherlands", "32": "Belgium", "33": "France",
    "34": "Spain", "36": "Hungary", "39": "Italy", "40": "Romania",
    "41": "Switzerland", "43": "Austria", "44": "United Kingdom", "45": "Denmark",
    "46": "Sweden", "47": "Norway", "48": "Poland", "49": "Germany",
    "51": "Peru", "52": "Mexico", "53": "Cuba", "54": "Argentina",
    "55": "Brazil", "56": "Chile", "57": "Colombia", "58": "Venezuela",
    "60": "Malaysia", "61": "Australia", "62": "Indonesia", "63": "Philippines",
    "64": "New Zealand", "65": "Singapore", "66": "Thailand", "81": "Japan",
    "82": "South Korea", "84": "Vietnam", "86": "China", "90": "Turkey",
    "91": "India", "92": "Pakistan", "93": "Afghanistan", "94": "Sri Lanka",
    "95": "Myanmar", "98": "Iran", "211": "South Sudan", "212": "Morocco",
    "213": "Algeria", "216": "Tunisia", "218": "Libya", "220": "Gambia",
    "221": "Senegal", "222": "Mauritania", "223": "Mali", "224": "Guinea",
    "225": "Cote d'Ivoire", "226": "Burkina Faso", "227": "Niger", "228": "Togo",
    "229": "Benin", "230": "Mauritius", "231": "Liberia", "232": "Sierra Leone",
    "233": "Ghana", "234": "Nigeria", "235": "Chad", "236": "Central African Republic",
    "237": "Cameroon", "238": "Cape Verde", "239": "Sao Tome and Principe", "240": "Equatorial Guinea",
    "241": "Gabon", "242": "Congo", "243": "DRC", "244": "Angola", "245": "Guinea Bissau",
    "249": "Sudan", "250": "Rwanda", "251": "Ethiopia", "252": "Somalia", "253": "Djibouti",
    "254": "Kenya", "255": "Tanzania", "256": "Uganda", "257": "Burundi",
    "258": "Mozambique", "260": "Zambia", "261": "Madagascar", "262": "Reunion",
    "263": "Zimbabwe", "264": "Namibia", "265": "Malawi", "266": "Lesotho",
    "267": "Botswana", "268": "Eswatini", "269": "Comoros", "291": "Eritrea",
    "350": "Gibraltar", "351": "Portugal", "352": "Luxembourg", "353": "Ireland",
    "354": "Iceland", "355": "Albania", "356": "Malta", "357": "Cyprus",
    "358": "Finland", "359": "Bulgaria", "370": "Lithuania", "371": "Latvia",
    "372": "Estonia", "373": "Moldova", "374": "Armenia", "375": "Belarus",
    "376": "Andorra", "377": "Monaco", "378": "San Marino", "379": "Vatican City",
    "380": "Ukraine", "381": "Serbia", "382": "Montenegro", "383": "Kosovo",
    "385": "Croatia", "386": "Slovenia", "387": "Bosnia and Herzegovina",
    "389": "North Macedonia", "420": "Czech Republic", "421": "Slovakia",
    "423": "Liechtenstein", "501": "Belize", "502": "Guatemala", "503": "El Salvador",
    "504": "Honduras", "505": "Nicaragua", "506": "Costa Rica", "507": "Panama",
    "509": "Haiti", "591": "Bolivia", "592": "Guyana", "593": "Ecuador",
    "595": "Paraguay", "597": "Suriname", "598": "Uruguay", "670": "Timor Leste",
    "673": "Brunei", "674": "Nauru", "675": "Papua New Guinea",
    "676": "Tonga", "677": "Solomon Islands", "678": "Vanuatu", "679": "Fiji",
    "680": "Palau", "685": "Samoa", "686": "Kiribati", "687": "New Caledonia",
    "688": "Tuvalu", "689": "French Polynesia", "691": "Micronesia",
    "692": "Marshall Islands", "850": "North Korea", "852": "Hong Kong",
    "853": "Macau", "855": "Cambodia", "856": "Laos", "880": "Bangladesh",
    "886": "Taiwan", "960": "Maldives", "961": "Lebanon", "962": "Jordan",
    "963": "Syria", "964": "Iraq", "965": "Kuwait", "966": "Saudi Arabia",
    "967": "Yemen", "968": "Oman", "970": "Palestine", "971": "UAE",
    "972": "Israel", "973": "Bahrain", "974": "Qatar", "975": "Bhutan",
    "976": "Mongolia", "977": "Nepal", "992": "Tajikistan", "993": "Turkmenistan",
    "994": "Azerbaijan", "995": "Georgia", "996": "Kyrgyzstan", "998": "Uzbekistan"
}

SERVICE_SHORTS = {
    "whatsapp": "WA", "facebook": "FB", "instagram": "IG", "telegram": "TG",
    "twitter": "TW", "google": "GO", "gmail": "GM", "youtube": "YT",
    "apple": "AP", "microsoft": "MS", "tiktok": "TT", "snapchat": "SC",
    "binance": "BN", "melbet": "MB", "bkash": "BK", "nagad": "NG",
    "imo": "IMO", "paypal": "PP", "uber": "UB", "amazon": "AMZ",
    "netflix": "NF", "discord": "DC", "spotify": "SP", "linkedin": "LI",
    "yahoo": "YH", "viber": "VB", "line": "LN", "wechat": "WC", "signal": "SG"
}

EMOJI_COLLECTION = {
    "whatsapp": "💚", "facebook": "📘", "instagram": "📷", "telegram": "✈️",
    "twitter": "𝕏", "google": "🔍", "gmail": "📧", "youtube": "🎬",
    "apple": "🍎", "microsoft": "💻", "tiktok": "🎵", "snapchat": "👻",
    "binance": "💰", "melbet": "🎰", "bkash": "💳", "nagad": "📲",
    "imo": "💭", "paypal": "💵", "uber": "🚗", "amazon": "📦",
    "netflix": "🎬", "discord": "💬", "spotify": "🎧", "linkedin": "💼",
    "yahoo": "📧", "viber": "💜", "line": "💚", "wechat": "💚", "signal": "🔒"
}

def get_country_flag(country_name):
    if not country_name: return "🌍"
    name = str(country_name).lower().strip()
    if name in COUNTRY_FLAGS: return COUNTRY_FLAGS[name]
    for country, flag in COUNTRY_FLAGS.items():
        if len(country) >= 4 and (country in name or name in country): return flag
    return "🌍"

def get_iso_code(country_name):
    name = str(country_name).lower().strip()
    if name in COUNTRY_ISO: return COUNTRY_ISO[name]
    for country, iso in COUNTRY_ISO.items():
        if country in name or name in country: return iso
    return name[:2].upper() if len(name) >= 2 else "UN"

def emo(keyword, default="✨"):
    if not keyword: return default
    kw = str(keyword).lower().strip()
    if kw in EMOJI_COLLECTION: return EMOJI_COLLECTION[kw]
    for key, emoji in EMOJI_COLLECTION.items():
        if len(key) >= 3 and key in kw: return emoji
    flag = get_country_flag(kw)
    if flag != "🌍": return flag
    return default

def get_short_service(service_name):
    name = str(service_name).lower().strip()
    if name in SERVICE_SHORTS: return SERVICE_SHORTS[name]
    return name[:2].upper() if len(name) >= 2 else "SV"

def mask_number(phone):
    phone_str = str(phone).replace('+', '')
    if len(phone_str) >= 6:
        return f"{phone_str[:3]}XXX{phone_str[-3:]}"
    return phone_str

def get_country_from_number(phone_number):
    number = str(phone_number).replace('+', '').strip()
    for code_len in [3, 2, 1]:
        if len(number) >= code_len:
            code = number[:code_len]
            if code in PHONE_TO_COUNTRY: return PHONE_TO_COUNTRY[code]
    return "Unknown"

def format_url(url):
    url = url.strip()
    if url and not url.startswith(('http://', 'https://', 'tg://')): return 'https://' + url
    return url

def extract_channel_identifier(url):
    url = url.strip()
    if url.lstrip('-').isdigit():
        return int(url)
    if url.startswith("@"):
        return url
    if "t.me/" in url:
        parts = url.split("t.me/")
        if len(parts) > 1:
            username = parts[1].split("/")[0].split("?")[0]
            if username.startswith("+"):
                return None
            if not username.startswith("@"):
                username = "@" + username
            return username
    return None

def is_private_invite_link(url):
    url = url.strip()
    if "t.me/+" in url or "t.me/joinchat/" in url:
        return True
    return False

def get_force_channel_link(ch):
    if isinstance(ch, dict):
        return ch.get("link", "")
    return ch

def get_force_channel_chat_id(ch):
    if isinstance(ch, dict):
        return ch.get("chat_id")
    return extract_channel_identifier(ch)

def get_force_channel_type(ch):
    if isinstance(ch, dict):
        return ch.get("chat_type", "channel")
    return "channel"

def detect_chat_type(chat_info):
    if chat_info and hasattr(chat_info, 'type'):
        if chat_info.type in ['group', 'supergroup']:
            return "group"
    return "channel"

def clean_html_tags(text):
    text = re.sub(r'<tg-emoji[^>]*>', '', text)
    text = re.sub(r'</tg-emoji>', '', text)
    return text

def safe_edit(chat_id, text, reply_markup=None, message_id=None):
    clean_text = clean_html_tags(text)
    target_msg_id = message_id if message_id else (menu_message_id.get(chat_id))
    if target_msg_id:
        for _attempt in range(2):
            try:
                return bot.edit_message_text(clean_text, chat_id=chat_id, message_id=target_msg_id, parse_mode="HTML", reply_markup=reply_markup)
            except Exception as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    return None
                if "message to edit not found" in err:
                    break
                if _attempt == 0 and ("timeout" in err or "connection" in err):
                    time.sleep(0.5)
                    continue
                break
    try:
        msg = bot.send_message(chat_id, clean_text, parse_mode="HTML", reply_markup=reply_markup)
        if msg: menu_message_id[chat_id] = msg.message_id
        return msg
    except: return None

def safe_edit_2fa(chat_id, text, reply_markup=None):
    try:
        clean_text = clean_html_tags(text)
        if chat_id in two_fa_message_id:
            return bot.edit_message_text(clean_text, chat_id=chat_id, message_id=two_fa_message_id[chat_id], parse_mode="HTML", reply_markup=reply_markup)
        else:
            msg = bot.send_message(chat_id, clean_text, parse_mode="HTML", reply_markup=reply_markup)
            if msg:
                two_fa_message_id[chat_id] = msg.message_id
            return msg
    except:
        return None

def safe_send(chat_id, text, reply_markup=None, reply_to=None):
    clean_text = clean_html_tags(text)
    for _attempt in range(2):
        try:
            msg = bot.send_message(chat_id, clean_text, parse_mode="HTML", reply_markup=reply_markup, reply_to_message_id=reply_to)
            if msg:
                menu_message_id[chat_id] = msg.message_id
            return msg
        except Exception as e:
            err = str(e).lower()
            if _attempt == 0 and ("timeout" in err or "connection" in err):
                time.sleep(0.5)
                continue
            return None

def load_data():
    with data_lock:
        if not os.path.exists(DATA_FILE):
            default_data = {
                "users": [], "services_data": {}, "forward_groups": [],
                "main_otp_link": "https://t.me/", "watermark": "DXA UNIVERSE",
                "force_join_enabled": False, "force_join_channels": [],
                "otp_counts": {}, "leaderboard": {},
                "balances": {}, "refers": {}, "withdrawals": [],
                "settings": {
                    "cooldown": 60,
                    "num_per_request": 5, "support_link": "https://t.me/ADMIN_ASIK"
                },
                "panels": {}, "apps": [], "month_sms": 0, "today_sms": 0, "sms_date": "",
                "traffic_log": {}, "extra_admins": [], "banned_users": [],
                "premium_users": [], "premium_type": "lifetime"
            }
            with open(DATA_FILE, "w", encoding='utf-8') as f: json.dump(default_data, f, indent=4)
            return default_data
        with open(DATA_FILE, "r", encoding='utf-8') as f:
            data = json.load(f)
            if "force_join_enabled" not in data: data["force_join_enabled"] = False
            if "force_join_channels" not in data: data["force_join_channels"] = []
            if "otp_counts" not in data: data["otp_counts"] = {}
            if "leaderboard" not in data: data["leaderboard"] = {}
            if "settings" not in data: 
                data["settings"] = {
                    "cooldown": 60,
                    "num_per_request": 5, "support_link": "https://t.me/ADMIN_ASIK"
                }
            if "panels" not in data: data["panels"] = {}
            if "apps" not in data: data["apps"] = DEFAULT_APPS
            if "month_sms" not in data: data["month_sms"] = 0
            if "today_sms" not in data: data["today_sms"] = 0
            if "sms_date" not in data: data["sms_date"] = ""
            if "traffic_log" not in data: data["traffic_log"] = {}
            if "extra_admins" not in data: data["extra_admins"] = []
            if "banned_users" not in data: data["banned_users"] = []
            if "premium_users" not in data: data["premium_users"] = []
            if "premium_type" not in data: data["premium_type"] = "lifetime"
            st = data.get("settings", {})
            if "num_per_request" not in st or st["num_per_request"] == 0:
                st["num_per_request"] = st.get("premium_num_per_request", 5)
            data["settings"] = st
            return data

def save_data(data):
    with data_lock:
        with open(DATA_FILE, "w", encoding='utf-8') as f: json.dump(data, f, indent=4)

def add_user(user_id):
    data = load_data()
    if user_id not in data.get("users", []):
        data.setdefault("users", []).append(user_id)
        save_data(data)
        total_users = len(data.get("users", []))
        try:
            user_info = bot.get_chat(user_id)
            first_name = html.escape(user_info.first_name or "User")
        except:
            first_name = "User"
        notify_text = (
            f"━━━━━━━━━━━━━━━\n"
            f"《 🆕 <b>NEW USER JOINED</b> 》\n"
            f"━━━━━━━━━━━━━━━\n"
            f"👤 <b>USER:</b> <a href='tg://user?id={user_id}'>{first_name}</a>\n"
            f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
            f"👥 <b>TOTAL USERS:</b> <code>{total_users}</code>\n"
            f"━━━━━━━━━━━━━━━"
        )
        try: safe_send(ADMIN_ID, notify_text)
        except: pass

def update_leaderboard(user_id, first_name):
    data = load_data()
    user_id_str = str(user_id)
    if "otp_counts" not in data: data["otp_counts"] = {}
    if "leaderboard" not in data: data["leaderboard"] = {}
    if user_id_str not in data["otp_counts"]: data["otp_counts"][user_id_str] = 0
    data["otp_counts"][user_id_str] += 1
    data["leaderboard"][user_id_str] = {"name": first_name or f"User{user_id}", "count": data["otp_counts"][user_id_str]}
    save_data(data)

def get_total_ranges():
    data = load_data()
    count = 0
    for panel in data.get("panels", {}).values():
        count += len(panel.get("ranges", {}))
    return count

def get_total_panels():
    data = load_data()
    return len(data.get("panels", {}))

def get_total_apps():
    data = load_data()
    return len(data.get("apps", []))

def get_total_available_numbers():
    data = load_data()
    total = 0
    for panel in data.get("panels", {}).values():
        if panel.get("status") != "active":
            continue
        # Check fetch type - if auto, they technically don't hold stock locally
        if panel.get("fetch_type", "manual") == "auto":
            continue
        for rng in panel.get("ranges", {}).values():
            total += len(rng.get("numbers", []))
    return total

def is_premium_user(user_id):
    return True

def get_premium_badge(user_id):
    return ""

def get_premium_type():
    data = load_data()
    return data.get("premium_type", "lifetime")

def _solve_math_captcha(html_text):
    """Extract and solve simple math captcha from login page HTML."""
    # Try specific operator patterns first
    m = re.search(r'(\d+)\s*[\+]\s*(\d+)\s*=\s*\?', html_text, re.IGNORECASE)
    if m:
        return str(int(m.group(1)) + int(m.group(2)))
    m = re.search(r'(\d+)\s*[-]\s*(\d+)\s*=\s*\?', html_text, re.IGNORECASE)
    if m:
        return str(int(m.group(1)) - int(m.group(2)))
    m = re.search(r'(\d+)\s*[*]\s*(\d+)\s*=\s*\?', html_text, re.IGNORECASE)
    if m:
        return str(int(m.group(1)) * int(m.group(2)))
    m = re.search(r'(\d+)\s*x\s*(\d+)\s*=\s*\?', html_text, re.IGNORECASE)
    if m:
        return str(int(m.group(1)) * int(m.group(2)))
    # "What is X + Y" style
    m = re.search(r'What\s+is\s+(\d+)\s*([+\-*x])\s*(\d+)', html_text, re.IGNORECASE)
    if m:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        if op == '+': return str(a + b)
        if op == '-': return str(a - b)
        if op in ('*', 'x'): return str(a * b)
    # Generic: "N op N" anywhere
    m = re.search(r'(\d+)\s*([+\-*x])\s*(\d+)', html_text)
    if m:
        a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
        if op == '+': return str(a + b)
        if op == '-': return str(a - b)
        if op in ('*', 'x'): return str(a * b)
    return None

def do_login_session(panel):
    login_url = panel.get("login_url", "")
    username = panel.get("login_user", "")
    password = panel.get("login_pass", "")
    if not login_url or not username:
        return None
    
    api_url = panel.get("api_url", "")
    api_fmt = panel.get("api_format", "")
    fmt = PANEL_FORMATS.get(api_fmt, {})
    
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        # For ints-type panels, handle form login with math captcha
        is_ints_type = api_fmt in ("ints", "ints_v2", "numberpanel", "sms_panel", "konekta", "timesms", "grand_panel", "pscall")
        
        if is_ints_type:
            # Step 1: GET the login page to extract captcha
            base_url = login_url.rstrip("/")
            # Remove trailing endpoint parts to get the actual base
            for suffix in ["/signin", "/signmein", "/login", "/api/login"]:
                if base_url.endswith(suffix):
                    base_url = base_url[:-len(suffix)]
                    break
            
            login_ep = fmt.get("login_endpoint", "/signin")
            full_login_url = f"{base_url}{login_ep}"
            
            try:
                page_res = session.get(full_login_url, timeout=15, allow_redirects=True)
                page_html = page_res.text
            except:
                page_html = ""
            
            # Step 2: Solve captcha if present
            captcha_answer = _solve_math_captcha(page_html) if page_html else None
            
            # Step 3: POST login with captcha
            login_data = {"username": username, "password": password}
            if captcha_answer:
                login_data["capt"] = captcha_answer
                login_data["captcha"] = captcha_answer
            
            # Try form POST first (common for ints panels)
            res = session.post(full_login_url, data=login_data, timeout=15, allow_redirects=True)
            
            # Check if login was successful
            # Success indicators: redirected to dashboard, no "error" in response, session cookies set
            login_success = False
            if res.status_code == 200:
                response_text = res.text.lower()
                # If we're on a dashboard page (not the login page), login succeeded
                if "dashboard" in response_text or "welcome" in response_text or "balance" in response_text:
                    login_success = True
                elif "logout" in response_text or "signout" in response_text:
                    login_success = True
                elif "error" not in response_text and "invalid" not in response_text and "failed" not in response_text:
                    if session.cookies and len(session.cookies) > 0:
                        login_success = True
            elif res.status_code in (301, 302):
                login_success = True
            
            if not login_success and session.cookies:
                # Try accessing a protected page to verify login
                try:
                    check_res = session.get(f"{base_url}/dashboard", timeout=10, allow_redirects=False)
                    if check_res.status_code == 200:
                        login_success = True
                    elif check_res.status_code in (301, 302):
                        loc = check_res.headers.get("location", "").lower()
                        if "login" not in loc and "signin" not in loc:
                            login_success = True
                except:
                    pass
            
            if login_success:
                # Try to extract token from page or API
                token = ""
                try:
                    token_match = re.search(r'token["\']?\s*[:=]\s*["\']([^"\']+)["\']', res.text)
                    if token_match:
                        token = token_match.group(1)
                except:
                    pass
                return {"session": session, "token": token, "cookies": dict(session.cookies)}
            
            # Try alternative login endpoints
            alt_endpoints = ["/signmein", "/signin", "/login"]
            for alt_ep in alt_endpoints:
                if alt_ep == login_ep:
                    continue
                try:
                    alt_url = f"{base_url}{alt_ep}"
                    alt_page = session.get(alt_url, timeout=10, allow_redirects=True)
                    if alt_page.status_code == 200 and "username" in alt_page.text.lower():
                        captcha_alt = _solve_math_captcha(alt_page.text)
                        alt_data = {"username": username, "password": password}
                        if captcha_alt:
                            alt_data["capt"] = captcha_alt
                            alt_data["captcha"] = captcha_alt
                        alt_res = session.post(alt_url, data=alt_data, timeout=15, allow_redirects=True)
                        if session.cookies and len(session.cookies) > 0:
                            alt_text = alt_res.text.lower()
                            if "error" not in alt_text and "invalid" not in alt_text:
                                return {"session": session, "token": "", "cookies": dict(session.cookies)}
                except:
                    continue
        
        # Standard API login (JSON-based)
        login_data = {"username": username, "password": password}
        res = session.post(login_url, json=login_data, timeout=15)
        if res.status_code == 200:
            try:
                resp_json = res.json()
                token = resp_json.get("token") or resp_json.get("access_token") or resp_json.get("session") or resp_json.get("key", "")
                if token:
                    return {"session": session, "token": token, "cookies": dict(session.cookies)}
            except:
                pass
            if session.cookies:
                return {"session": session, "token": "", "cookies": dict(session.cookies)}
        
        # Try form-encoded POST
        res2 = session.post(login_url, data={"username": username, "password": password}, timeout=15)
        if res2.status_code == 200:
            if session.cookies:
                return {"session": session, "token": "", "cookies": dict(session.cookies)}
            try:
                resp_json2 = res2.json()
                token2 = resp_json2.get("token") or resp_json2.get("access_token") or resp_json2.get("key", "")
                if token2:
                    return {"session": session, "token": token2, "cookies": {}}
            except:
                pass
    except:
        pass
    return None

def get_login_session(panel_id):
    if panel_id in login_sessions:
        return login_sessions[panel_id]
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if not panel:
        return None
    result = do_login_session(panel)
    if result:
        login_sessions[panel_id] = result
    return result

def increment_sms_count():
    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")
    if data.get("sms_date") != today:
        data["sms_date"] = today
        data["today_sms"] = 0
    data["today_sms"] = data.get("today_sms", 0) + 1
    data["month_sms"] = data.get("month_sms", 0) + 1
    save_data(data)

def check_force_join(user_id):
    if user_id == ADMIN_ID: return True
    data = load_data()
    if not data.get("force_join_enabled"): return True
    channels = data.get("force_join_channels", [])
    if not channels: return True
    for ch in channels:
        ch_id = get_force_channel_chat_id(ch)
        if ch_id is None: continue
        try:
            member = bot.get_chat_member(ch_id, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except:
            return False
    return True

# ==================== MENU MARKUPS ====================

def get_main_menu(user_id):
    data = load_data()
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(rbtn("📱 GET NUMBER", "primary"), rbtn("📊 TRAFFIC", "success"))
    markup.add(rbtn("🔐 2FA ONLINE", "danger"), rbtn("🏆 LEADERBOARD", "primary"))
    markup.add(rbtn("📈 STOCK INFO", "success"), rbtn("🛠️ SUPPORT", "primary"))
    if user_id == ADMIN_ID or user_id in data.get("extra_admins", []):
        markup.add(rbtn("⚙️ ADMIN PANEL", "danger"))
    return markup

def get_2fa_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(ibtn("🔐 GENERATE 2FA CODE", callback_data="2fa_generate", style="primary"),
               ibtn("🔙 BACK TO MAIN MENU", callback_data="2fa_back", style="danger"))
    return markup

def get_leaderboard_menu():
    markup = InlineKeyboardMarkup()
    markup.add(ibtn("🔄 REFRESH", callback_data="refresh_leaderboard", style="primary"))
    markup.add(ibtn("❌ CLOSE", callback_data="close_menu", style="danger"))
    return markup

def get_admin_menu(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(ibtn("📋 MANAGE PANELS", callback_data="admin_manage_panels", style="success"),
               ibtn("📦 MANAGE APPS", callback_data="admin_manage_apps", style="primary"))
    markup.add(ibtn("⚙️ SYSTEM", callback_data="admin_system", style="danger"),
               ibtn("👤 USER VIEW", callback_data="admin_user_view", style="primary"))
    markup.add(ibtn("📢 BROADCAST", callback_data="admin_broadcast", style="danger"),
               ibtn("🔗 OTP GROUPS", callback_data="admin_group_settings", style="primary"))
    markup.add(ibtn("📣 FORCE JOIN", callback_data="admin_force_join", style="success"),
               ibtn("💎 WATERMARK", callback_data="admin_set_watermark", style="primary"))
    if user_id == ADMIN_ID:
        markup.add(ibtn("👮 MANAGE ADMIN", callback_data="admin_manage_admins", style="danger"))
    markup.add(ibtn("❌ CLOSE", callback_data="close_menu", style="danger"))
    return markup

def get_force_join_menu():
    data = load_data()
    is_enabled = data.get("force_join_enabled", False)
    channels = data.get("force_join_channels", [])
    status_text = "🟢 ENABLED" if is_enabled else "🔴 DISABLED"
    status_style = "success" if is_enabled else "danger"
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(ibtn(f"TOGGLE: {status_text}", callback_data="toggle_force_join", style=status_style))
    color_cycle = ["primary", "success", "danger"]
    for idx, ch in enumerate(channels):
        display = get_force_channel_link(ch) if get_force_channel_link(ch) else str(get_force_channel_chat_id(ch))
        ch_type_str = get_force_channel_type(ch)
        if ch_type_str == "group":
            type_icon = "👥"
            type_label = "GROUP"
        else:
            type_icon = "📢"
            type_label = "CHANNEL"
        is_priv = isinstance(ch, dict) and is_private_invite_link(ch.get("link", ""))
        priv_icon = "🔒" if is_priv else "🌐"
        markup.add(ibtn(f"❌ {type_icon}{priv_icon} {type_label}: {display}", callback_data=f"delfjc_{idx}", style=color_cycle[idx % 3]))
    markup.add(ibtn("➕ ADD CHANNEL/GROUP", callback_data="add_fjc", style="primary"))
    markup.add(ibtn("🔙 BACK", callback_data="back_to_admin", style="success"))
    return markup

def get_group_settings_menu():
    data = load_data()
    markup = InlineKeyboardMarkup(row_width=1)
    otp_link = data.get("main_otp_link", "")
    markup.add(ibtn("🔗 SET OTP GROUP LINK", callback_data="set_main_otp_link", style="primary"))
    if otp_link and otp_link != "https://t.me/":
        markup.add(ibtn("🗑️ REMOVE OTP LINK", callback_data="del_main_otp_link", style="danger"))
    markup.add(ibtn("➕ ADD FORWARD GROUP", callback_data="add_fwd_group", style="success"))
    fwd_groups = data.get("forward_groups", [])
    if fwd_groups:
        color_cycle_grp = ["primary", "success", "danger"]
        for g_idx, grp in enumerate(fwd_groups):
            btn_count = len(grp.get('buttons', []))
            markup.add(ibtn(f"⚙️ {grp['chat_id']} [{btn_count} BTNS]", callback_data=f"editgrp_{grp['chat_id']}", style=color_cycle_grp[g_idx % 3]))
    markup.add(ibtn("🔙 BACK", callback_data="back_to_admin", style="primary"))
    return markup

def show_edit_group_menu(chat_id, grp_id, message_id=None):
    data = load_data()
    grp = next((g for g in data.get("forward_groups", []) if str(g["chat_id"]) == str(grp_id)), None)
    if not grp:
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>GROUP SETTINGS</b> 》", get_group_settings_menu(), message_id)
        return
    text = f"━━━━━━━━━━━━━━━\n《 ⚙️ MANAGE GROUP 》\n━━━━━━━━━━━━━━━\n📱 ID: <code>{grp_id}</code>\n🔘 BUTTONS: {len(grp.get('buttons', []))}"
    markup = InlineKeyboardMarkup(row_width=1)
    for idx, btn in enumerate(grp.get("buttons", [])):
        markup.add(ibtn(f"❌ {btn['name']}", callback_data=f"delgrpbtn_{grp_id}_{idx}", style="danger"))
    markup.add(ibtn("➕ ADD BUTTON", callback_data=f"addgrpbtn_{grp_id}", style="success"))
    markup.add(ibtn("🗑️ DELETE GROUP", callback_data=f"delfwd_{grp_id}", style="danger"))
    markup.add(ibtn("🔙 BACK", callback_data="admin_group_settings", style="primary"))
    safe_edit(chat_id, text, markup, message_id)

def show_panel_list(chat_id, message_id=None):
    data = load_data()
    markup = InlineKeyboardMarkup(row_width=1)
    color_cycle = ["primary", "success", "danger"]
    for idx, (panel_id, panel) in enumerate(data.get("panels", {}).items()):
        status_icon = "🟢" if panel.get("status") == "active" else "🔴"
        rng_count = len(panel.get("ranges", {}))
        f_type = panel.get("fetch_type", "manual")
        
        # Display number counts only for manual panels
        if f_type == "manual":
            total_nums = sum(len(r.get("numbers", [])) for r in panel.get("ranges", {}).values())
            btn_text = f"{status_icon} [MANUAL] {panel['name'].upper()} | R:{rng_count} N:{total_nums}"
        else:
            btn_text = f"{status_icon} [AUTO] {panel['name'].upper()} | R:{rng_count} (API)"
            
        markup.add(ibtn(btn_text, callback_data=f"panel_view|{panel_id}", style=color_cycle[idx % 3]))
        
    markup.add(ibtn("➕ Add Panel", callback_data="add_panel", style="success"))
    markup.add(ibtn("🔙 Back to Admin", callback_data="back_to_admin", style="primary"))
    
    total_panels = len(data.get('panels', {}))
    # Count numbers only for manual panels
    total_all_nums = sum(sum(len(r.get("numbers", [])) for r in p.get("ranges", {}).values()) for p in data.get("panels", {}).values() if p.get("fetch_type", "manual") == "manual")
    
    text = f"┌─────────────────┐\n│ 📋 <b>API Panels</b>\n├─────────────────┤\n│ Total Panels: <code>{total_panels}</code>\n│ Total Manual Numbers: <code>{total_all_nums}</code>\n└─────────────────┘"
    safe_edit(chat_id, text, markup, message_id)

def show_panel_detail(chat_id, panel_id, message_id=None):
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if not panel:
        show_panel_list(chat_id, message_id)
        return
    status_icon = "🟢" if panel.get("status") == "active" else "🔴"
    status_text = "Active" if panel.get("status") == "active" else "Inactive"
    p_type = panel.get("type", "api")
    f_type = panel.get("fetch_type", "manual").title()
    rng_count = len(panel.get("ranges", {}))
    
    api_fmt = panel.get("api_format", detect_panel_format(panel.get("api_url", ""), panel.get("api_key", "")))
    fmt_label = PANEL_FORMATS.get(api_fmt, {}).get("label", api_fmt.upper())
    
    if p_type == "api":
        type_label = "🔌 API Panel"
        api_url = panel.get("api_url", "Not set")
        api_connected = "✅ Connected" if panel.get("api_key") else "❌ Not set"
        creds_line = f"🔑 API: {api_connected}\n│ 🌐 URL: {html.escape(str(api_url))}"
    else:
        type_label = "🔐 Login Panel"
        login_url = panel.get("login_url", "Not set")
        login_active = "✅ Active" if panel.get("login_user") else "❌ Not set"
        creds_line = f"🔐 Login: {login_active}\n│ 🌐 URL: {html.escape(str(login_url))}"
        
    if f_type.lower() == "manual":
        total_nums = sum(len(r.get("numbers", [])) for r in panel.get("ranges", {}).values())
        num_str = str(total_nums)
    else:
        num_str = "Auto API (Dynamic)"

    text = (
        f"┌─────────────────┐\n"
        f"│ 🔧 <b>{html.escape(panel['name'])}</b>\n"
        f"├─────────────────┤\n"
        f"│ <b>Type:</b> {type_label}\n"
        f"│ <b>Format:</b> {fmt_label}\n"
        f"│ <b>Generation:</b> {f_type}\n"
        f"│ <b>Status:</b> {status_icon} {status_text}\n"
        f"│ {creds_line}\n"
        f"│ 📱 <b>Ranges:</b> {rng_count}\n"
        f"│ 🔢 <b>Total Numbers:</b> {num_str}\n"
        f"└─────────────────┘"
    )
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(ibtn("🔍 Test Connection", callback_data=f"panel_test|{panel_id}", style="primary"))
    if p_type == "api":
        markup.add(ibtn("🔑 Set API Creds", callback_data=f"panel_setcreds|{panel_id}", style="success"))
    else:
        markup.add(ibtn("🔐 Set Login Creds", callback_data=f"panel_setlogin|{panel_id}", style="success"))
    markup.add(ibtn(f"📋 Format: {api_fmt.upper()}", callback_data=f"panel_format|{panel_id}", style="primary"))
    markup.add(ibtn("📱 View Ranges", callback_data=f"panel_ranges|{panel_id}", style="primary"),
               ibtn("✏️ Rename", callback_data=f"panel_rename|{panel_id}", style="success"))
    toggle_text = "🔴 Deactivate" if panel.get("status") == "active" else "🟢 Activate"
    markup.add(ibtn(toggle_text, callback_data=f"panel_toggle|{panel_id}", style="danger"),
               ibtn("❌ Delete Panel", callback_data=f"panel_delete|{panel_id}", style="danger"))
    if p_type == "api":
        markup.add(ibtn("🔐 Switch to Login Creds", callback_data=f"panel_switch|{panel_id}", style="primary"))
    else:
        markup.add(ibtn("🔌 Switch to API Creds", callback_data=f"panel_switch|{panel_id}", style="primary"))
    markup.add(ibtn("🔙 Back to Panels", callback_data="admin_manage_panels", style="success"))
    safe_edit(chat_id, text, markup, message_id)

def show_panel_format_menu(chat_id, panel_id, message_id=None):
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if not panel: return
    current = panel.get("api_format", detect_panel_format(panel.get("api_url", ""), panel.get("api_key", "")))
    markup = InlineKeyboardMarkup(row_width=1)
    for fmt_name, fmt_data in PANEL_FORMATS.items():
        check = " \u2705" if current == fmt_name else ""
        style = "success" if current == fmt_name else "primary"
        markup.add(ibtn(f"{fmt_data['label']}{check}", callback_data=f"set_pfmt|{panel_id}|{fmt_name}", style=style))
    markup.add(ibtn("\ud83d\udd27 Set Custom Endpoints", callback_data=f"panel_custom_ep|{panel_id}", style="danger"))
    markup.add(ibtn("\ud83d\udd19 Back", callback_data=f"panel_view|{panel_id}", style="success"))
    safe_edit(chat_id, f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\u300a \ud83d\udccb <b>API FORMAT</b> \u300b\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n<b>Panel:</b> {html.escape(panel['name'])}\n<b>Current:</b> {current.upper()}\n\n<b>SELECT FORMAT:</b>", markup, message_id)

def process_custom_endpoints(message, panel_id, msg_id):
    if message.text == '/cancel': return show_panel_detail(message.chat.id, panel_id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    lines = message.text.strip().split("\n")
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if panel:
        panel["api_format"] = "custom"
        panel["custom_endpoints"] = {
            "get_number": lines[0].strip() if len(lines) > 0 else "",
            "get_sms": lines[1].strip() if len(lines) > 1 else "",
            "get_latest_sms": lines[2].strip() if len(lines) > 2 else ""
        }
        save_data(data)
        safe_send(message.chat.id, f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\u2705 <b>Custom endpoints saved!</b>\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
    show_panel_detail(message.chat.id, panel_id)

def _auto_configure_panel(api_url, api_key):
    """Auto-detect panel format, clean URL, and test real API endpoints. Returns dict with config info."""
    detected_fmt = detect_panel_format(api_url, api_key)
    clean_url = _get_api_base(api_url, detected_fmt)
    fmt_label = PANEL_FORMATS.get(detected_fmt, {}).get("label", detected_fmt.upper())
    
    result = {
        "api_url": clean_url,
        "original_url": api_url,
        "api_format": detected_fmt,
        "fmt_label": fmt_label,
        "test_ok": False,
        "test_msg": "",
        "test_status": 0,
    }
    
    headers = {}
    fmt = PANEL_FORMATS.get(detected_fmt, PANEL_FORMATS["standard"])
    auth_header = fmt.get("auth_header", "X-API-Key")
    if auth_header and api_key:
        headers[auth_header] = api_key
    
    # Try real API endpoints based on detected format
    test_endpoints = []
    if detected_fmt == "ins_agent":
        test_endpoints = [
            f"{clean_url}/api/functions/agent-api/otp?limit=1",
            f"{clean_url}/api/functions/agent-api/stats",
        ]
    elif detected_fmt == "lamix":
        from datetime import datetime as _dt
        _today = _dt.now().strftime("%Y-%m-%d")
        test_endpoints = [
            f"{clean_url}/viewstats?token={api_key}&dt1={_today} 00:00:00&dt2={_today} 23:59:59&records=1",
        ]
    elif detected_fmt in ("ints", "ints_v2"):
        test_endpoints = [
            f"{clean_url}/api/getServices",
            f"{clean_url}/api/getBalance",
        ]
    elif detected_fmt == "numberpanel":
        test_endpoints = [
            f"{clean_url}/api/getServices",
            f"{clean_url}/api/getBalance",
        ]
    elif detected_fmt == "sms_panel":
        test_endpoints = [
            f"{clean_url}/api/getServices",
            f"{clean_url}/api/getBalance",
        ]
    else:
        test_endpoints = [
            f"{clean_url}/api/getServices",
            f"{clean_url}/api/getBalance",
        ]
    
    # Also try the clean base URL itself
    test_endpoints.append(clean_url)
    
    for ep in test_endpoints:
        try:
            res = req_session.get(ep, headers=headers, timeout=10)
            if res.status_code == 200:
                try:
                    data = res.json()
                    result["test_ok"] = True
                    result["test_msg"] = f"API Working ({ep.split(clean_url)[-1] or '/'})"
                    result["test_status"] = 200
                    return result
                except:
                    pass
            elif res.status_code < 500:
                result["test_status"] = res.status_code
        except:
            continue
    
    # If no endpoint returned JSON 200, still mark as configured
    if result["test_status"] > 0:
        result["test_msg"] = f"Server reachable (Status: {result['test_status']})"
    else:
        result["test_msg"] = "Could not reach server"
    return result

def test_panel_connection(chat_id, panel_id, message_id=None):
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if not panel:
        return
    
    p_type = panel.get("type", "api")
    api_url = panel.get("api_url", "")
    api_key = panel.get("api_key", "")
    api_fmt = panel.get("api_format", detect_panel_format(api_url, api_key))
    fmt_label = PANEL_FORMATS.get(api_fmt, {}).get("label", api_fmt.upper())
    f_type = panel.get("fetch_type", "manual")
    
    results = []
    results.append(f"┌─────────────────────┐")
    results.append(f"│  🔍 <b>CONNECTION TEST</b>  │")
    results.append(f"└─────────────────────┘")
    results.append(f"📋 Panel: <b>{html.escape(panel.get('name', ''))}</b>")
    results.append(f"🔧 Format: <b>{fmt_label}</b>")
    results.append(f"🌐 Type: <b>{p_type.upper()}</b> / <b>{f_type.upper()}</b>")
    results.append("")
    
    # Step 1: Test credentials
    if p_type == "api":
        if not api_url or not api_key:
            results.append("❌ <b>API credentials not set!</b>")
            safe_send(chat_id, "\n".join(results))
            show_panel_detail(chat_id, panel_id, message_id)
            return
        
        headers = get_api_headers(panel)
        
        # Auto-configure and test real API endpoints
        config = _auto_configure_panel(api_url, api_key)
        if config["api_url"] != api_url.rstrip("/"):
            panel["api_url"] = config["api_url"]
            panel["api_format"] = config["api_format"]
            save_data(data)
            results.append(f"🔄 <b>URL Auto-Fixed:</b> <code>{html.escape(config['api_url'])}</code>")
        
        if config["test_ok"]:
            results.append(f"✅ <b>API Connected</b> — {config['test_msg']}")
        elif config["test_status"] > 0:
            results.append(f"⚠️ <b>API Status:</b> {config['test_msg']}")
        else:
            results.append(f"❌ <b>Connection Error:</b> {config['test_msg']}")
            safe_send(chat_id, "\n".join(results))
            show_panel_detail(chat_id, panel_id, message_id)
            return
    else:
        login_url = panel.get("login_url", "")
        username = panel.get("login_user", "")
        if not login_url or not username:
            results.append("❌ <b>Login credentials not set!</b>")
            safe_send(chat_id, "\n".join(results))
            show_panel_detail(chat_id, panel_id, message_id)
            return
        try:
            login_sessions.pop(panel_id, None)
            sess = do_login_session(panel)
            if sess:
                login_sessions[panel_id] = sess
                token_status = "Token" if sess.get("token") else "Cookies"
                results.append(f"✅ <b>Login OK!</b> Auth: {token_status}")
                headers = {}
                if sess.get("token"):
                    headers = {'Authorization': f'Bearer {sess["token"]}'}
                
                results.append(f"🔗 <b>Panel URL:</b> <code>{html.escape(api_url or login_url)[:60]}</code>")
            else:
                results.append("❌ <b>Login Failed!</b>")
                results.append("<i>Check URL and credentials</i>")
                safe_send(chat_id, "\n".join(results))
                show_panel_detail(chat_id, panel_id, message_id)
                return
        except Exception as e:
            results.append(f"❌ <b>Login Failed:</b> {str(e)[:80]}")
            safe_send(chat_id, "\n".join(results))
            show_panel_detail(chat_id, panel_id, message_id)
            return
    
    results.append("")
    
    # Step 2: Test each range
    ranges = panel.get("ranges", {})
    if not ranges:
        results.append("ℹ️ <b>No ranges to test</b>")
    else:
        results.append(f"<b>📱 Testing {len(ranges)} Range(s):</b>")
        results.append("")
        
        for rng_id, rng in ranges.items():
            rng_name = rng.get("name", "Unknown")
            rng_code = rng.get("range_code", "N/A")
            api_cc = rng.get("country_code", rng_name)
            app = rng.get("app", "N/A")
            flag = get_country_flag(rng_name)
            
            results.append(f"{flag} <b>{rng_name}</b> | {app}")
            results.append(f"  Service: <code>{rng_code}</code> | Country: <code>{api_cc}</code>")
            
            if f_type == "auto":
                try:
                    if p_type == "api":
                        hdr = get_api_headers(panel)
                    else:
                        s = get_login_session(panel_id)
                        hdr = {'Authorization': f'Bearer {s["token"]}'} if s and s.get("token") else {}
                    
                    test_ep = build_api_url(panel, "get_number", service=rng_code, country=api_cc)
                    if not test_ep:
                        test_ep = f"{api_url}/getNumber?service={rng_code}&country={api_cc}"
                    
                    results.append(f"  🔗 URL: <code>{html.escape(test_ep[:120])}</code>")
                    
                    fmt = PANEL_FORMATS.get(api_fmt, PANEL_FORMATS["standard"])
                    http_method = fmt.get("http_method", "GET").upper()
                    
                    if http_method == "POST":
                        post_body_template = fmt.get("post_body")
                        if post_body_template:
                            body = copy.deepcopy(post_body_template)
                            for bk in body:
                                if isinstance(body[bk], str):
                                    body[bk] = body[bk].replace("{service}", rng_code).replace("{country}", api_cc)
                            post_hdr = dict(hdr)
                            post_hdr["Content-Type"] = "application/json"
                            res = req_session.post(test_ep, headers=post_hdr, json=body, timeout=15)
                            results.append(f"  📤 Body: <code>{html.escape(str(body))}</code>")
                        else:
                            res = req_session.post(test_ep, headers=hdr, timeout=15)
                    else:
                        res = req_session.get(test_ep, headers=hdr, timeout=15)
                    
                    results.append(f"  📡 Status: <code>{res.status_code}</code>")
                    
                    if res.status_code == 200:
                        try:
                            rj = res.json()
                            resp_preview = str(rj)[:200]
                            results.append(f"  📦 Response: <code>{html.escape(resp_preview)}</code>")
                            
                            # Try to extract number
                            parsed = parse_number_response(panel, rj)
                            if parsed["success"] and parsed["number"]:
                                got_num = parsed["number"]
                                results.append(f"  ✅ Got Number: <code>+{got_num}</code>")
                                
                                # Validate country
                                detected = get_country_from_number(str(got_num).replace('+', ''))
                                expected = rng_name
                                results.append(f"  🌍 Expected: {expected} | Got: {detected}")
                                
                                if detected.lower() != expected.lower() and detected != "Universal":
                                    results.append(f"  ⚠️ <b>COUNTRY MISMATCH!</b>")
                                    results.append(f"  💡 <i>Check service/country codes</i>")
                                else:
                                    results.append(f"  ✅ <b>Country Match OK!</b>")
                            else:
                                results.append(f"  ⚠️ No number in response")
                        except:
                            results.append(f"  ⚠️ Non-JSON response: <code>{html.escape(res.text[:100])}</code>")
                    else:
                        try:
                            results.append(f"  ⚠️ Error: <code>{html.escape(res.text[:100])}</code>")
                        except:
                            results.append(f"  ⚠️ HTTP Error {res.status_code}")
                except Exception as e:
                    results.append(f"  ❌ Error: {html.escape(str(e)[:80])}")
            else:
                nums = rng.get("numbers", [])
                used = rng.get("used_numbers", [])
                avail = len([n for n in nums if n not in used])
                results.append(f"  📊 Manual: {avail}/{len(nums)} available")
            results.append("")
    
    final_text = "\n".join(results)
    if len(final_text) > 4000:
        final_text = final_text[:4000] + "\n..."
    safe_send(chat_id, final_text)
    show_panel_detail(chat_id, panel_id, message_id)

def show_panel_ranges(chat_id, panel_id, message_id=None):
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if not panel:
        return
    ranges = panel.get("ranges", {})
    f_type = panel.get("fetch_type", "manual")
    markup = InlineKeyboardMarkup(row_width=1)
    color_cycle = ["primary", "success", "danger"]
    text_lines = []
    
    for idx, (rng_id, rng) in enumerate(ranges.items()):
        nums = rng.get("numbers", [])
        total = len(nums)
        flag = get_country_flag(rng.get("name", ""))
        app_name = rng.get("app", "?").upper()
        rng_code = rng.get("range_code", "NA")
        
        api_cc = rng.get("country_code", "")
        cc_label = f" | CC:{api_cc}" if api_cc else ""
        
        if f_type == "manual":
            status_icon = "🟢" if total > 0 else "🔴"
            text_lines.append(f"{status_icon} {flag} {rng['name']} | {app_name} ({rng_code}){cc_label} | {total} nums")
            markup.add(ibtn(f"🔧 {flag} {rng['name']} [{total}]", callback_data=f"view_range|{panel_id}|{rng_id}", style=color_cycle[idx % 3]))
        else:
            text_lines.append(f"🟢 {flag} {rng['name']} | {app_name} ({rng_code}){cc_label} | AUTO API")
            markup.add(ibtn(f"🔧 {flag} {rng['name']} [API]", callback_data=f"view_range|{panel_id}|{rng_id}", style=color_cycle[idx % 3]))
            
    markup.add(ibtn("➕ Add Range", callback_data=f"add_range|{panel_id}", style="success"))
    markup.add(ibtn("🔙 Back to Panel", callback_data=f"panel_view|{panel_id}", style="primary"))
    header = f"━━━━━━━━━━━━━━━\n《 📱 <b>Ranges — {html.escape(panel['name'])}</b> 》\n━━━━━━━━━━━━━━━"
    if text_lines:
        body = "\n".join(text_lines)
        text = f"{header}\n{body}"
    else:
        if f_type == "auto":
            text = f"{header}\n<b>No ranges added yet.</b>\n\n\u26a0\ufe0f <i>Add ranges with Country + Service + Country Code</i>\n<i>to start fetching numbers from API.</i>"
        else:
            text = f"{header}\n<b>No ranges added yet.</b>\n<i>Add ranges and then add numbers for this panel.</i>"
    safe_edit(chat_id, text, markup, message_id)

def show_range_detail(chat_id, panel_id, rng_id, message_id=None):
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if not panel:
        return
    rng = panel.get("ranges", {}).get(rng_id)
    if not rng:
        show_panel_ranges(chat_id, panel_id, message_id)
        return
        
    f_type = panel.get("fetch_type", "manual")
    flag = get_country_flag(rng.get("name", ""))
    rng_code = rng.get("range_code", "N/A")
    api_cc = rng.get("country_code", "N/A")
    
    if f_type == "manual":
        nums = rng.get("numbers", [])
        used = rng.get("used_numbers", [])
        avail = len([n for n in nums if n not in used])
        cycle_status = "🟢 Active" if len(nums) > 0 else "🔴 Empty"
        text = (
            f"┌─────────────────┐\n"
            f"│ 📱 <b>{flag} {html.escape(rng['name'])}</b>\n"
            f"├─────────────────┤\n"
            f"│ 📦 App: <b>{rng.get('app', 'N/A').upper()}</b>\n"
            f"│ 🔗 Service Code: <code>{rng_code}</code>\n"
            f"│ 🌍 Country Code: <code>{api_cc}</code>\n"
            f"│ 📊 Total Added: <code>{len(nums)}</code>\n"
            f"│ ✅ Available: <code>{avail}</code>\n"
            f"│ 🔄 Served: <code>{len(used)}</code>\n"
            f"│ ♻️ Status: {cycle_status}\n"
            f"│ 💡 <i>Numbers auto-recycle when all served</i>\n"
            f"└─────────────────┘"
        )
    else:
        text = (
            f"┌─────────────────┐\n"
            f"│ 📱 <b>{flag} {html.escape(rng['name'])}</b>\n"
            f"├─────────────────┤\n"
            f"│ 📦 App: <b>{rng.get('app', 'N/A').upper()}</b>\n"
            f"│ 🔗 Service Code: <code>{rng_code}</code>\n"
            f"│ 🌍 Country Code: <code>{api_cc}</code>\n"
            f"│ 🤖 Type: <b>Auto API (Direct Fetch)</b>\n"
            f"│ 💡 <i>Numbers fetched from API directly</i>\n"
            f"└─────────────────┘"
        )
        
    markup = InlineKeyboardMarkup(row_width=2)
    
    if f_type == "manual":
        markup.add(ibtn("➕ Add Numbers", callback_data=f"add_nums|{panel_id}|{rng_id}", style="success"))
    markup.add(ibtn("❌ Delete Range", callback_data=f"del_range|{panel_id}|{rng_id}", style="danger"))
    markup.add(ibtn("🔙 Back", callback_data=f"panel_ranges|{panel_id}", style="primary"))
    safe_edit(chat_id, text, markup, message_id)

def show_app_list(chat_id, message_id=None):
    data = load_data()
    apps = data.get("apps", DEFAULT_APPS)
    markup = InlineKeyboardMarkup(row_width=1)
    color_cycle = ["primary", "success", "danger"]
    for idx, app in enumerate(apps):
        markup.add(ibtn(f"❌ {emo(app)} {app}", callback_data=f"del_app|{app}", style=color_cycle[idx % 3]))
    markup.add(ibtn("➕ Add App", callback_data="add_app", style="success"))
    markup.add(ibtn("🔙 Back to Admin", callback_data="back_to_admin", style="primary"))
    text = f"┌─────────────────┐\n│ 📦 <b>App Management</b>\n├─────────────────┤\n│ Total Apps: <code>{len(apps)}</code>\n│ <i>Tap to remove</i>\n└─────────────────┘"
    safe_edit(chat_id, text, markup, message_id)


# ==================== HANDLERS ====================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    
    add_user(user_id)
    if not check_force_join(user_id):
        show_force_join_message(chat_id, message.message_id)
        return
    show_main_menu(chat_id, message.from_user.first_name, message.message_id)

def show_force_join_message(chat_id, reply_to=None):
    data = load_data()
    channels = data.get("force_join_channels", [])
    text = f"━━━━━━━━━━━━━━━\n《 ⚠️ <b>ACCESS DENIED</b> 》\n━━━━━━━━━━━━━━━\n📢 <b>JOIN OUR CHANNELS TO USE THIS BOT</b>\n\n<b>CLICK JOINED AFTER JOINING</b>"
    markup = InlineKeyboardMarkup()
    color_cycle = ["primary", "success", "danger"]
    for idx, ch in enumerate(channels):
        link = get_force_channel_link(ch)
        ch_type = get_force_channel_type(ch)
        if ch_type == "group":
            btn_label = "👥 JOIN GROUP"
        else:
            btn_label = "📢 JOIN CHANNEL"
        if link:
            markup.add(ibtn(text=btn_label, url=link, style=color_cycle[idx % 3]))
    markup.add(ibtn(text="✅ JOINED ✅", callback_data="check_join", style="success"))
    safe_send(chat_id, text, markup, reply_to=reply_to)

@bot.message_handler(content_types=['document'])
def handle_document(message):
    if message.chat.type != 'private':
        return

@bot.message_handler(func=lambda m: user_states.get(m.chat.id, {}).get("active_flow") is not None)
def handle_active_flow(message):
    """Handles text messages during active multi-step flows (add_range, etc.)"""
    if message.chat.type != 'private':
        return
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    flow = state.get("active_flow")
    
    if not message.text:
        try: bot.delete_message(chat_id, message.message_id)
        except: pass
        return
    
    try: bot.delete_message(chat_id, message.message_id)
    except: pass
    bot.clear_step_handler_by_chat_id(chat_id)
    
    if message.text.strip() == '/cancel':
        panel_id = state.get("add_range_panel", "")
        msg_id = state.get("add_range_msg_id")
        user_states.pop(chat_id, None)
        if panel_id:
            show_panel_ranges(chat_id, panel_id, msg_id)
        else:
            show_main_menu(chat_id)
        return
    
    if flow == "add_range_country":
        _flow_add_range_country(message)
    elif flow == "add_range_service":
        _flow_add_range_service(message)
    elif flow == "add_range_cc":
        _flow_add_range_cc(message)
    else:
        user_states.pop(chat_id, None)
        show_main_menu(chat_id)

def _flow_add_range_country(message):
    """Step 1/4: Process country name input"""
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    panel_id = state.get("add_range_panel", "")
    msg_id = state.get("add_range_msg_id")
    
    country_name = message.text.strip()
    state["add_range_name"] = country_name
    state["active_flow"] = None  # Clear flow - Step 2 is callback-based
    user_states[chat_id] = state
    
    markup = InlineKeyboardMarkup(row_width=2)
    color_cycle = ["primary", "success", "danger"]
    for idx, app in enumerate(load_data().get("apps", DEFAULT_APPS)):
        markup.add(ibtn(f"{emo(app)} {app}", callback_data=f"rng_app_select|{panel_id}|{app}", style=color_cycle[idx % 3]))
    markup.add(ibtn("🔙 Back", callback_data=f"panel_ranges|{panel_id}", style="primary"))
    safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n✅ <b>Country:</b> {html.escape(country_name)}\n━━━━━━━━━━━━━━━\n<b>Step 2/4: Select App/Server for this country:</b>", markup, msg_id)

def _flow_add_range_service(message):
    """Step 3/4: Process service code input"""
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    panel_id = state.get("add_range_panel", "")
    msg_id = state.get("add_range_msg_id")
    
    range_code = message.text.strip()
    state["add_range_code"] = range_code
    state["active_flow"] = "add_range_cc"  # Next step: country code
    user_states[chat_id] = state
    
    rng_name = state.get("add_range_name", "Range")
    iso = get_iso_code(rng_name)
    
    markup = InlineKeyboardMarkup().add(ibtn("🔙 Back", callback_data=f"panel_ranges|{panel_id}", style="primary"))
    safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🌍 <b>Country Code</b> 》\n━━━━━━━━━━━━━━━\n<b>Step 4/4: Send API Country Code</b>\n\n✅ Country: <code>{html.escape(rng_name)}</code>\n✅ Service: <code>{html.escape(range_code)}</code>\n\n<b>Send the country code/ID used by this API panel</b>\n\n<b>Examples:</b>\n<code>{iso}</code> or <code>ci</code> or <code>225</code> or <code>0</code>\n\n<i>Check your panel docs for correct country code</i>", markup, msg_id)

def _flow_add_range_cc(message):
    """Step 4/4: Process country code input and save range"""
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    panel_id = state.get("add_range_panel", "")
    msg_id = state.get("add_range_msg_id")
    
    country_code = message.text.strip()
    range_code = state.get("add_range_code", "")
    rng_name = state.get("add_range_name", "Range")
    app_name = state.get("add_range_app", "App")
    
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    
    if panel:
        rng_id = "r_" + str(uuid.uuid4())[:8]
        panel.setdefault("ranges", {})[rng_id] = {
            "name": rng_name,
            "app": app_name,
            "range_code": range_code,
            "country_code": country_code,
            "numbers": [],
            "used_numbers": []
        }
        save_data(data)
        bot.send_message(chat_id, f"✅ Range added!\n📍 Country: {rng_name}\n📱 Service: {range_code}\n🌍 Country Code: {country_code}\n📦 App: {app_name}", parse_mode="HTML")
    
    user_states.pop(chat_id, None)
    show_panel_ranges(chat_id, panel_id, msg_id)

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    if message.chat.type != 'private':
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text
    
    try: bot.delete_message(chat_id, message.message_id)
    except: pass
    
    try:
        if chat_id in menu_message_id:
            bot.delete_message(chat_id, menu_message_id[chat_id])
            del menu_message_id[chat_id]
    except: pass
    
    bot.clear_step_handler_by_chat_id(chat_id)
    add_user(user_id)
    
    data = load_data()
    if user_id in data.get("banned_users", []):
        safe_send(chat_id, "━━━━━━━━━━━━━━━\n《 🚫 <b>ACCOUNT BANNED</b> 》\n━━━━━━━━━━━━━━━\n<b>YOU ARE BANNED BY ADMIN!</b>")
        return
    
    if not check_force_join(user_id):
        show_force_join_message(chat_id)
        return

    if "GET NUMBER" in text or "📱" in text: show_user_services(chat_id)
    elif "TRAFFIC" in text or "📊" in text: show_traffic_info(chat_id)
    elif "SUPPORT" in text or "🛠️" in text: show_support(chat_id, message.from_user.first_name)
    elif "2FA ONLINE" in text or "🔐" in text: show_2fa_menu_display(chat_id)
    elif "LEADERBOARD" in text or "🏆" in text: show_leaderboard(chat_id)
    elif "STOCK INFO" in text or "📈" in text: show_stock_info(chat_id)
    elif ("ADMIN PANEL" in text or "⚙️" in text) and (user_id == ADMIN_ID or user_id in data.get("extra_admins", [])): show_admin_panel(chat_id)

# ==================== DISPLAY FUNCTIONS ====================

def show_main_menu(chat_id, first_name=None, reply_to=None):
    if not first_name:
        try: first_name = bot.get_chat(chat_id).first_name
        except: first_name = "VIP User"
    data = load_data()
    watermark = data.get("watermark", "DXA UNIVERSE")
    st = data.get("settings", {})
    text = (
        f"┌─────────────────────┐\n"
        f"│  👑 <b>NUMBER BOT</b>  │\n"
        f"└─────────────────────┘\n"
        f"\n"
        f"👋 <b>WELCOME,</b> <a href='tg://user?id={chat_id}'>{html.escape(first_name)}</a>!\n\n"
        f"📱 <b>GET NUMBER</b> — OTP SERVICE\n"
        f"📊 <b>TRAFFIC</b> — LIVE NETWORK\n"
        f"🔐 <b>2FA ONLINE</b> — AUTHENTICATOR\n"
        f"🏆 <b>LEADERBOARD</b> — TOP USERS\n"
        f"📈 <b>STOCK INFO</b> — CHECK STOCK\n"
        f"🛠️ <b>SUPPORT</b> — CONTACT ADMIN\n"
        f"━━━━━━━━━━━━━━━\n"
        f"永 <b>POWERED BY {html.escape(watermark)}</b> 🔴"
    )
    msg = safe_send(chat_id, text, get_main_menu(chat_id), reply_to=reply_to)
    if msg: menu_message_id[chat_id] = msg.message_id

def show_user_services(chat_id):
    data = load_data()
    markup = InlineKeyboardMarkup(row_width=2)
    color_cycle = ["primary", "success", "danger"]
    apps = data.get("apps", DEFAULT_APPS)
    st = data.get("settings", {})
    
    num_per_req = st.get("num_per_request", 5)
    if num_per_req <= 0:
        num_per_req = 5
    
    if not apps or num_per_req == 0:
        markup.add(ibtn("❌ CLOSE", callback_data="close_menu", style="danger"))
        safe_edit(chat_id, "━━━━━━━━━━━━━━━\n《 ⚠️ <b>NOT CONFIGURED</b> 》\n━━━━━━━━━━━━━━━\n<b>ADMIN HAS NOT SET UP THE SERVICE YET</b>\n<b>PLEASE WAIT FOR ADMIN TO CONFIGURE</b>", markup)
        return
    
    buttons = []
    for idx, app_name in enumerate(apps):
        has_stock = False
        for panel in data.get("panels", {}).values():
            if panel.get("status") != "active": continue
            for rng in panel.get("ranges", {}).values():
                if rng.get("app", "").upper() == app_name.upper():
                    if panel.get("fetch_type", "manual") == "auto" or rng.get("numbers", []):
                        has_stock = True; break
            if has_stock: break
            
        if has_stock:
            buttons.append(ibtn(text=f"{emo(app_name)} {app_name.upper()}", callback_data=f"usr_app|{app_name}", style=color_cycle[idx % 3]))
            
    if buttons: markup.add(*buttons)
    else:
        markup.add(ibtn("⚠️ NO SERVICE AVAILABLE", callback_data="ignore", style="danger"))
    markup.add(ibtn("❌ CANCEL", callback_data="close_menu", style="danger"))
    data_wm = data.get("watermark", "DXA UNIVERSE")
    safe_edit(chat_id, f"┌─────────────────────┐\n│  ⭐ <b>SERVER SELECTION</b>  │\n└─────────────────────┘\n\n🔍 <b>CHOOSE YOUR SERVICE BELOW</b>\n⚡ <b>FAST • SECURE • RELIABLE</b>\n\n永 <b>{html.escape(data_wm)}</b>", markup)

def show_user_countries(chat_id, app_name, message_id=None):
    data = load_data()
    countries = {}
    
    for panel_id, panel in data.get("panels", {}).items():
        if panel.get("status") != "active":
            continue
        for rng_id, rng in panel.get("ranges", {}).items():
            if rng.get("app", "").upper() == app_name.upper():
                cname = rng.get("name", "Unknown")
                key = cname.lower()
                if key not in countries:
                    countries[key] = {"name": cname, "count": 0, "entries": []}
                
                if panel.get("fetch_type", "manual") == "auto":
                    countries[key]["count"] = "API"
                else:
                    all_nums = rng.get("numbers", [])
                    if all_nums and countries[key]["count"] != "API":
                        countries[key]["count"] += len(all_nums)
                        
                countries[key]["entries"].append({"panel_id": panel_id, "rng_id": rng_id})
    
    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    color_cycle = ["primary", "success", "danger"]
    for idx, (key, cdata) in enumerate(countries.items()):
        if cdata["count"] == 0: continue
        flag = get_country_flag(cdata["name"])
        count_display = "API" if cdata["count"] == "API" else cdata["count"]
        buttons.append(ibtn(text=f"{flag} {cdata['name'].upper()} [{count_display}]", callback_data=f"usr_cnt|{app_name}|{key}", style=color_cycle[idx % 3]))
    
    if buttons:
        markup.add(*buttons)
    markup.add(ibtn("🔙 BACK", callback_data="back_to_user_services", style="success"), ibtn("❌ CLOSE", callback_data="close_menu", style="danger"))
    text = f"┌─────────────────────┐\n│  🌍 <b>SELECT COUNTRY</b>  │\n└─────────────────────┘\n\n{emo(app_name)} <b>SERVER:</b> <code>{html.escape(app_name.upper())}</code>\n\n📍 <b>CHOOSE YOUR COUNTRY:</b>"
    safe_edit(chat_id, text, markup, message_id)



def show_2fa_menu_display(chat_id):
    text = f"━━━━━━━━━━━━━━━\n《 🔐 <b>2FA AUTHENTICATOR</b> 》\n━━━━━━━━━━━━━━━\n🔐 <b>GENERATE SECURE 2FA CODES</b>\n📱 <b>ENTER YOUR SECRET KEY</b>\n\n<b>CLICK GENERATE 2FA CODE BELOW</b>"
    safe_edit(chat_id, text, get_2fa_menu())

def show_traffic_info(chat_id):
    data = load_data()
    traffic_log = data.get("traffic_log", {})
    
    if not traffic_log:
        markup = InlineKeyboardMarkup()
        markup.add(ibtn("🔄 REFRESH", callback_data="refresh_traffic", style="primary"))
        markup.add(ibtn("❌ CLOSE", callback_data="close_menu", style="danger"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 📊 <b>NETWORK TRAFFIC</b> 》\n━━━━━━━━━━━━━━━\n<b>No traffic data yet.</b>", markup)
        return
    
    lines = []
    lines.append("┌─────────────────┐")
    lines.append("│  📶 <b>NETWORK TRAFFIC</b>  │")
    lines.append("└─────────────────┘")
    lines.append("")
    
    for app_name, countries in traffic_log.items():
        app_emoji = emo(app_name)
        lines.append(f"[ {app_emoji} <b>{html.escape(app_name)}</b> ]")
        lines.append("")
        sorted_countries = sorted(countries.items(), key=lambda x: x[1], reverse=True)
        for country_name, success_count in sorted_countries:
            flag = get_country_flag(country_name)
            iso = get_iso_code(country_name)
            lines.append(f"├─ {flag} <b>{html.escape(country_name)} ({iso})</b>")
            lines.append(f"│  └ Success: {success_count}")
        lines.append("")
    
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    
    markup = InlineKeyboardMarkup()
    markup.add(ibtn("🔄 REFRESH", callback_data="refresh_traffic", style="primary"))
    markup.add(ibtn("❌ CLOSE", callback_data="close_menu", style="danger"))
    safe_edit(chat_id, text, markup)

def log_traffic(app_name, country_name):
    """Log a successful OTP to traffic data."""
    if not app_name or not country_name:
        return
    data = load_data()
    traffic = data.setdefault("traffic_log", {})
    app_key = app_name.title()
    country_key = country_name.title()
    if app_key not in traffic:
        traffic[app_key] = {}
    traffic[app_key][country_key] = traffic[app_key].get(country_key, 0) + 1
    save_data(data)

def show_support(chat_id, first_name):
    text = (
        f"┏━━━━━━━ 🌙 ━━━━━━━┓\n"
        f"═《 <b>𝗦𝗨𝗣𝗣𝗢𝗥𝗧</b> 》═\n"
        f"━━━━━━━━━━━━━\n"
        f"👋 <b>𝗛𝗘𝗟𝗟𝗢,</b> <a href='tg://user?id={chat_id}'>{html.escape(first_name)}</a>!\n"
        f"💬 <b>𝗪𝗘𝗟𝗖𝗢𝗠𝗘 𝗧𝗢 𝗦𝗨𝗣𝗣𝗢𝗥𝗧 𝗣𝗔𝗡𝗘𝗟</b>\n"
        f"➤ <b>𝗧𝗘𝗟𝗟 𝗠𝗘 𝗛𝗢𝗪 𝗖𝗔𝗡 𝗜 𝗛𝗘𝗟𝗣 𝗬𝗢𝗨</b>\n"
        f"➤ <b>𝗧𝗔𝗣 𝗦𝗨𝗣𝗣𝗢𝗥𝗧 𝗕𝗨𝗧𝗧𝗢𝗡</b>\n"
        f"➤ <b>𝗧𝗢 𝗖𝗢𝗡𝗧𝗔𝗖𝗧 𝗔𝗗𝗠𝗜𝗡!</b>\n"
        f"┗━━━━━━━ ⚡ ━━━━━━━┛"
    )
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(ibtn("🎧 SUPPORT", url="https://t.me/sadhin8miya", style="success"), ibtn("🔙 BACK", callback_data="close_menu", style="danger"))
    safe_edit(chat_id, text, markup)

def show_leaderboard(chat_id, message_id=None):
    data = load_data()
    leaderboard = data.get("leaderboard", {})
    text = "━━━━━━━━━━━━━━━\n《 🏆 <b>LEADERBOARD</b> 》\n━━━━━━━━━━━━━━━\n\n"
    if not leaderboard:
        text += "<b>⚠️ NO DATA YET</b>\n\n<b>BE THE FIRST TO GET OTP!</b>"
    else:
        sorted_lb = sorted(leaderboard.items(), key=lambda x: x[1]["count"], reverse=True)[:10]
        stylish_nums = ["➊", "➋", "➌", "➍", "➎", "➏", "➐", "➑", "➒", "➓"]
        for idx, (uid, udata) in enumerate(sorted_lb):
            name = html.escape(udata.get("name", "User"))
            count = udata.get("count", 0)
            mention = f"<a href='tg://user?id={uid}'>{name}</a>"
            text += f"{stylish_nums[idx]}  {mention}  —  {count} OTP\n"
            text += "━━━━━━━━━━━━━━━\n"
    watermark = data.get("watermark", "DXA UNIVERSE")
    text += f"\n🚀 <b>POWERED BY {html.escape(watermark)}</b>\n━━━━━━━━━━━━━━━"
    safe_edit(chat_id, text, get_leaderboard_menu(), message_id)

def show_admin_panel(chat_id, message_id=None):
    data = load_data()
    today = datetime.now().strftime("%Y-%m-%d")
    if data.get("sms_date") != today:
        data["today_sms"] = 0
    avail_nums = get_total_available_numbers()
    st = data.get("settings", {})
    active_panels = sum(1 for p in data.get("panels", {}).values() if p.get("status") == "active")
    total_panels = get_total_panels()
    watermark = data.get("watermark", "DXA UNIVERSE")
    text = (
        f"┌─────────────────────┐\n"
        f"│  👑 <b>ADMIN CONTROL PANEL</b>  │\n"
        f"└─────────────────────┘\n"
        f"\n"
        f"┌── <b>📊 Statistics</b>\n"
        f"│  👥 Users: <code>{len(data.get('users', []))}</code>\n"
        f"│  👮 Admins: <code>{len(data.get('extra_admins', []))}</code>\n"
        f"│  📢 OTP Groups: <code>{len(data.get('forward_groups', []))}</code>\n"
        f"├── <b>🔧 Infrastructure</b>\n"
        f"│  📋 Panels: <code>{active_panels}/{total_panels}</code>\n"
        f"│  📦 Apps: <code>{get_total_apps()}</code>\n"
        f"│  📱 Ranges: <code>{get_total_ranges()}</code>\n"
        f"│  🔢 Available: <code>{avail_nums}</code>\n"
        f"├── <b>📈 Activity</b>\n"
        f"│  📅 Month: <code>{data.get('month_sms', 0)}</code> SMS\n"
        f"│  📊 Today: <code>{data.get('today_sms', 0)}</code> SMS\n"
        f"├── <b>⚙️ Config</b>\n"
        f"│  ⏳ Cooldown: <code>{st.get('cooldown', 60)}s</code>\n"
        f"│  📱 Num/Req: <code>{st.get('num_per_request', 5)}</code>\n"
        f"└─────────────────────┘\n"
        f"永 <b>{html.escape(watermark)}</b>"
    )
    safe_edit(chat_id, text, get_admin_menu(chat_id), message_id)

def show_admin_system(chat_id, message_id=None):
    data = load_data()
    st = data.get("settings", {})
    markup = InlineKeyboardMarkup(row_width=2)
    
    markup.add(ibtn(f"⏳ COOLDOWN: {st.get('cooldown', 60)}s", callback_data="sys_cool", style="danger"),
               ibtn(f"📱 NUM/REQ: {st.get('num_per_request', 5)}", callback_data="sys_num_req", style="success"))
    markup.add(ibtn("🛠️ SUPPORT LINK", callback_data="sys_sup", style="primary"))
    markup.add(ibtn("🔙 BACK", callback_data="back_to_admin", style="success"))
    
    text = (
        f"━━━━━━━━━━━━━━━\n"
        f"《 ⚙️ <b>SYSTEM SETTINGS</b> 》\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔧 <b>SETTINGS:</b>\n"
        f"  ⏳ Cooldown: <code>{st.get('cooldown', 60)}s</code>\n"
        f"  📱 Num/Req: <code>{st.get('num_per_request', 5)}</code>\n"
        f"  🛠️ Support: <code>{html.escape(st.get('support_link', 'https://t.me/ADMIN_ASIK'))}</code>\n"
        f"━━━━━━━━━━━━━━━"
    )
    safe_edit(chat_id, text, markup, message_id)

def show_user_view(chat_id, message_id=None):
    data = load_data()
    users = len(data.get("users", []))
    verified = len(data.get("otp_counts", {}).keys())
    banned = len(data.get("banned_users", []))
    
    text = (
        f"━━━━━━━━━━━━━━━\n"
        f"《 👤 <b>USER VIEW</b> 》\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 <b>LIVE STATISTICS:</b>\n\n"
        f"👥 <b>TOTAL USERS:</b> <b>{users}</b>\n"
        f"✅ <b>VERIFIED USERS:</b> <b>{verified}</b>\n"
        f"🚫 <b>BANNED USERS:</b> <b>{banned}</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🕒 <b>UPDATED:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(ibtn("💎 USER PROFILE", callback_data="uv_profile", style="primary"),
               ibtn("🚫 BAN / UNBAN", callback_data="uv_ban_menu", style="danger"))
    markup.add(ibtn("🔙 BACK", callback_data="back_to_admin", style="success"))
    safe_edit(chat_id, text, markup, message_id)

def show_stock_info(chat_id, message_id=None):
    data = load_data()
    stock_data = {}
    total_avail = 0
    
    for panel in data.get("panels", {}).values():
        if panel.get("status") != "active":
            continue
        # Only count stock for Manual panels
        if panel.get("fetch_type", "manual") == "auto":
            continue
            
        for rng in panel.get("ranges", {}).values():
            app = rng.get("app", "UNKNOWN").upper()
            cname = rng.get("name", "Unknown").title()
            nums = rng.get("numbers", [])
            used = rng.get("used_numbers", [])
            avail = len([n for n in nums if n not in used])
            
            if avail > 0:
                if app not in stock_data:
                    stock_data[app] = {}
                stock_data[app][cname] = stock_data[app].get(cname, 0) + avail
                total_avail += avail

    text = f"━━━━━━━━━━━━━━━\n《 📈 <b>STOCK INFO</b> 》\n━━━━━━━━━━━━━━━\n"
    
    if not stock_data:
        text += "\n<b>⚠️ NO MANUAL STOCK AVAILABLE!</b>\n<b>PLEASE ADD NUMBERS IN PANELS.</b>\n"
    else:
        for app, countries in stock_data.items():
            text += f"\n📦 <b>APP: {emo(app)} {app}</b>\n"
            for country, count in sorted(countries.items(), key=lambda x: x[1], reverse=True):
                flag = get_country_flag(country)
                text += f" ├ {flag} <b>{country}:</b> <code>{count}</code> nums\n"
    
    text += f"\n━━━━━━━━━━━━━━━\n📊 <b>TOTAL AVAILABLE:</b> <code>{total_avail}</code>\n━━━━━━━━━━━━━━━"
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(ibtn("🔄 REFRESH", callback_data="refresh_stock", style="success"),
               ibtn("❌ CLOSE", callback_data="close_menu", style="danger"))
    safe_edit(chat_id, text, markup, message_id)

# ==================== CALLBACK HANDLER ====================

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    try: bot.answer_callback_query(call.id)
    except: pass

    user_id = call.from_user.id
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if call.data == "ignore": return

    # Only clear step handlers for navigation callbacks, not for input-related ones
    nav_prefixes = ("back_to", "admin_", "panel_view", "panel_ranges", "close_menu", "add_panel")
    if any(call.data.startswith(p) for p in nav_prefixes):
        bot.clear_step_handler_by_chat_id(chat_id)

    try:
        _handle_query_inner(call, user_id, chat_id, msg_id)
    except Exception as e:
        try:
            bot.answer_callback_query(call.id, f"⚠️ Error: {str(e)[:50]}", show_alert=True)
        except: pass

def _handle_query_inner(call, user_id, chat_id, msg_id):
    data = load_data()

    if call.data == "refresh_leaderboard": show_leaderboard(chat_id, msg_id); return
    if call.data == "refresh_stock": show_stock_info(chat_id, msg_id); return

    # 2FA
    if call.data == "2fa_back":
        try: bot.delete_message(chat_id, msg_id)
        except: pass
        if chat_id in menu_message_id:
            del menu_message_id[chat_id]
        show_main_menu(chat_id)
        return
    elif call.data == "2fa_refresh":
        key = user_states.get(chat_id, {}).get('2fa_key')
        if key: process_2fa_refresh_logic(chat_id, key)
        else: bot.answer_callback_query(call.id, "❌ NO KEY FOUND!", show_alert=True)
        return
    elif call.data == "2fa_generate":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="2fa_back", style="primary"))
        text = f"━━━━━━━━━━━━━━━\n《 🔑 ENTER 2FA KEY 》\n━━━━━━━━━━━━━━━\n📝 SEND YOUR 2FA SECRET KEY\n\nEXAMPLE: <code>JBSWY3DPEHPK3PXP</code>"
        safe_edit(chat_id, text, markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_2fa_code)
        return
    elif call.data == "2fa_new_key":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="2fa_back", style="primary"))
        text = f"━━━━━━━━━━━━━━━\n《 🔑 ENTER NEW 2FA KEY 》\n━━━━━━━━━━━━━━━\n📝 SEND YOUR NEW SECRET KEY\n\nEXAMPLE: <code>JBSWY3DPEHPK3PXP</code>"
        safe_edit_2fa(chat_id, text, markup)
        bot.register_next_step_handler_by_chat_id(chat_id, process_2fa_code)
        return

    if call.data == "check_join":
        if check_force_join(user_id):
            wm = data.get("watermark", "DXA UNIVERSE")
            bot.answer_callback_query(call.id, f"✅ Welcome to {wm}!", show_alert=True)
            try: bot.delete_message(chat_id, msg_id)
            except: pass
            if chat_id in menu_message_id:
                del menu_message_id[chat_id]
            show_main_menu(chat_id)
        else:
            bot.answer_callback_query(call.id, "❌ Please join the channel first!", show_alert=True)
        return

    if call.data == "close_menu":
        try: bot.delete_message(chat_id, msg_id)
        except: pass
        if chat_id in menu_message_id:
            del menu_message_id[chat_id]
        show_main_menu(chat_id)
        return

    # Admin check
    admin_restricted_prefixes = ["adm_", "add_", "del_", "editgrp_", "delfjc_", "delfwd_", "delgrpbtn_", "deladm_", "addgrpbtn_", "unban_", "sys_", "panel_", "rng_app_select|", "add_range|", "view_range|", "del_range|", "del_app|", "add_nums|", "reset_used|", "set_pfmt|"]
    admin_restricted_exact = ["admin_broadcast", "admin_group_settings", "admin_set_watermark", "admin_force_join", "toggle_force_join", "add_fjc", "back_to_admin", "admin_system", "admin_user_view", "admin_manage_panels", "admin_manage_apps", "admin_manage_admins", "add_panel", "add_app", "add_new_admin", "uv_profile", "uv_ban_menu", "uv_ban_do", "uv_unban_list", "set_main_otp_link", "del_main_otp_link", "add_fwd_group"]
    if any(call.data.startswith(x) for x in admin_restricted_prefixes) or call.data in admin_restricted_exact:
        if user_id != ADMIN_ID and user_id not in data.get("extra_admins", []):
            return bot.answer_callback_query(call.id, "⚠️ ACCESS DENIED", show_alert=True)

    # Navigation
    if call.data == "back_to_admin":
        user_states.pop(chat_id, None)
        show_admin_panel(chat_id, msg_id)
    elif call.data == "admin_system": show_admin_system(chat_id, msg_id)
    elif call.data == "admin_user_view": show_user_view(chat_id, msg_id)

    elif call.data == "uv_profile":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="admin_user_view", style="success"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 💎 <b>USER PROFILE</b> 》\n━━━━━━━━━━━━━━━\n<b>📝 SEND USER ID TO VIEW PROFILE:</b>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_user_profile, msg_id)
    elif call.data == "uv_ban_menu":
        show_ban_unban_menu(chat_id, msg_id)
    elif call.data == "uv_ban_do":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="uv_ban_menu", style="success"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔨 <b>BAN USER</b> 》\n━━━━━━━━━━━━━━━\n<b>SEND USER ID TO BAN:</b>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_do_ban, msg_id)
    elif call.data == "uv_unban_list":
        show_unban_list(chat_id, msg_id)
    elif call.data.startswith("unban_"):
        uid = int(call.data.split("_")[1])
        if uid in data.get("banned_users", []):
            data["banned_users"].remove(uid)
            save_data(data)
            bot.answer_callback_query(call.id, f"✅ USER {uid} UNBANNED!", show_alert=True)
        show_unban_list(chat_id, msg_id)
    elif call.data == "admin_manage_panels":
        show_panel_list(chat_id, msg_id)
    
    # --- PANEL CREATION TYPE ---
    elif call.data == "add_panel":
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(ibtn("📝 Manual (Admin Adds Nums)", callback_data="add_pnl_type|manual", style="primary"),
                   ibtn("🤖 Auto API (Direct Fetch)", callback_data="add_pnl_type|auto", style="success"))
        markup.add(ibtn("🔙 Back to Panels", callback_data="admin_manage_panels", style="danger"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔧 <b>Choose Panel Type</b> 》\n━━━━━━━━━━━━━━━\nSelect how numbers will be handled in this panel:", markup, msg_id)
        
    elif call.data.startswith("add_pnl_type|"):
        p_type = call.data.split("|")[1]
        user_states[chat_id] = {"new_panel_fetch_type": p_type}
        markup = InlineKeyboardMarkup().add(ibtn("🔙 Back to Panels", callback_data="admin_manage_panels", style="primary"))
        type_str = "Manual (Txt)" if p_type == "manual" else "Auto API"
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔧 <b>Add Panel [{type_str}] — Step 1/3</b> 》\n━━━━━━━━━━━━━━━\n<b>Enter a name for this panel:</b>\n\n<b>Example:</b> Premium SMS", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_add_panel_step1, msg_id)

    elif call.data.startswith("panel_view|"):
        panel_id = call.data.split("|")[1]
        show_panel_detail(chat_id, panel_id, msg_id)
    elif call.data.startswith("panel_test|"):
        panel_id = call.data.split("|")[1]
        test_panel_connection(chat_id, panel_id, msg_id)
    elif call.data.startswith("panel_setcreds|"):
        panel_id = call.data.split("|")[1]
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data=f"panel_view|{panel_id}", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔑 <b>Set API Creds — Step 1/2</b> 》\n━━━━━━━━━━━━━━━\n<b>Send the API URL:</b>\n\n<b>Example:</b> https://yourpanel.com/api/sms", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_set_api_url, panel_id, msg_id)
    elif call.data.startswith("panel_ranges|"):
        panel_id = call.data.split("|")[1]
        if chat_id in user_states and user_states[chat_id].get("active_flow"):
            user_states.pop(chat_id, None)
        show_panel_ranges(chat_id, panel_id, msg_id)
    elif call.data.startswith("panel_rename|"):
        panel_id = call.data.split("|")[1]
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data=f"panel_view|{panel_id}", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 ✏️ <b>Rename Panel</b> 》\n━━━━━━━━━━━━━━━\n<b>Send new name:</b>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_rename_panel, panel_id, msg_id)
    elif call.data.startswith("panel_toggle|"):
        panel_id = call.data.split("|")[1]
        panel = data.get("panels", {}).get(panel_id)
        if panel:
            panel["status"] = "inactive" if panel.get("status") == "active" else "active"
            save_data(data)
        show_panel_detail(chat_id, panel_id, msg_id)
    elif call.data.startswith("panel_delete|"):
        panel_id = call.data.split("|")[1]
        if panel_id in data.get("panels", {}):
            del data["panels"][panel_id]
            save_data(data)
        bot.answer_callback_query(call.id, "Panel deleted!", show_alert=True)
        show_panel_list(chat_id, msg_id)
    elif call.data.startswith("panel_format|"):
        panel_id = call.data.split("|")[1]
        show_panel_format_menu(chat_id, panel_id, msg_id)
    elif call.data.startswith("set_pfmt|"):
        parts = call.data.split("|")
        panel_id, fmt_name = parts[1], parts[2]
        panel = data.get("panels", {}).get(panel_id)
        if panel:
            panel["api_format"] = fmt_name
            save_data(data)
        bot.answer_callback_query(call.id, f"Format set to {fmt_name.upper()}!", show_alert=True)
        show_panel_detail(chat_id, panel_id, msg_id)
    elif call.data.startswith("panel_custom_ep|"):
        panel_id = call.data.split("|")[1]
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data=f"panel_view|{panel_id}", style="success"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔧 <b>CUSTOM ENDPOINTS</b> 》\n━━━━━━━━━━━━━━━\nSend 3 lines:\n1. Get Number URL path\n2. Get SMS URL path\n3. Get Latest SMS URL path\n\n<b>Use placeholders:</b>\n<code>{{api_key}}</code> <code>{{service}}</code> <code>{{country}}</code> <code>{{number_id}}</code>\n\n<b>Example:</b>\n<code>/api/v1/get?key={{api_key}}&amp;srv={{service}}</code>\n<code>/api/v1/sms/{{number_id}}?key={{api_key}}</code>\n<code>/api/v1/latest?key={{api_key}}</code>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_custom_endpoints, panel_id, msg_id)
    elif call.data.startswith("panel_switch|"):
        panel_id = call.data.split("|")[1]
        panel = data.get("panels", {}).get(panel_id)
        if panel:
            if panel.get("type") == "api":
                panel["type"] = "login"
            else:
                panel["type"] = "api"
            login_sessions.pop(panel_id, None)
            save_data(data)
        show_panel_detail(chat_id, panel_id, msg_id)
    elif call.data.startswith("panel_setlogin|"):
        panel_id = call.data.split("|")[1]
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data=f"panel_view|{panel_id}", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔐 <b>Set Login Creds — Step 1/2</b> 》\n━━━━━━━━━━━━━━━\n<b>Send the Login URL:</b>\n\n<b>Example:</b> http://45.82.67.20/ints/login", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_set_login_url, panel_id, msg_id)
    
    # ADDD RANGE 
    elif call.data.startswith("add_range|"):
        panel_id = call.data.split("|")[1]
        user_states[chat_id] = {
            "active_flow": "add_range_country",
            "add_range_panel": panel_id,
            "add_range_msg_id": msg_id
        }
        markup = InlineKeyboardMarkup().add(ibtn("🔙 Back", callback_data=f"panel_ranges|{panel_id}", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 📱 <b>Add Range</b> 》\n━━━━━━━━━━━━━━━\n<b>Step 1/4: Send Country Name</b>\n\n<b>Example:</b> India", markup, msg_id)
    
    elif call.data.startswith("rng_app_select|"):
        parts = call.data.split("|")
        panel_id, app_name = parts[1], parts[2]
        state = user_states.setdefault(chat_id, {})
        state["add_range_app"] = app_name
        state["active_flow"] = "add_range_service"
        state["add_range_msg_id"] = msg_id
        user_states[chat_id] = state
        markup = InlineKeyboardMarkup().add(ibtn("🔙 Back", callback_data=f"panel_ranges|{panel_id}", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>Service Code</b> 》\n━━━━━━━━━━━━━━━\n<b>Step 3/4: Send Service Code (API)</b>\n\n<b>Example:</b> <code>fb</code> or <code>ig</code> or <code>wa</code>\n<i>(The service code used by the API panel)</i>", markup, msg_id)

    elif call.data.startswith("add_nums|"):
        parts = call.data.split("|")
        panel_id, rng_id = parts[1], parts[2]
        rng_name = data.get("panels", {}).get(panel_id, {}).get("ranges", {}).get(rng_id, {}).get("name", "Range")
        markup = InlineKeyboardMarkup().add(ibtn("🔙 Back", callback_data=f"view_range|{panel_id}|{rng_id}", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 ➕ <b>Add Numbers to {html.escape(rng_name)}</b> 》\n━━━━━━━━━━━━━━━\n<b>Send numbers one per line or comma separated:</b>\n\n<code>923001234567</code>\n<code>923009876543</code>\n\n<b>Or send a .txt file with numbers.</b>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_add_numbers_to_range, panel_id, rng_id, msg_id)
    elif call.data.startswith("reset_used|"):
        parts = call.data.split("|")
        panel_id, rng_id = parts[1], parts[2]
        panel = data.get("panels", {}).get(panel_id)
        if panel:
            rng = panel.get("ranges", {}).get(rng_id)
            if rng:
                rng["used_numbers"] = []
                save_data(data)
        bot.answer_callback_query(call.id, "Used numbers reset!", show_alert=True)
        show_range_detail(chat_id, panel_id, rng_id, msg_id)
    elif call.data.startswith("del_range|"):
        parts = call.data.split("|")
        panel_id, rng_id = parts[1], parts[2]
        panel = data.get("panels", {}).get(panel_id)
        if panel and rng_id in panel.get("ranges", {}):
            del panel["ranges"][rng_id]
            save_data(data)
        show_panel_ranges(chat_id, panel_id, msg_id)
    elif call.data.startswith("view_range|"):
        parts = call.data.split("|")
        panel_id, rng_id = parts[1], parts[2]
        show_range_detail(chat_id, panel_id, rng_id, msg_id)
    elif call.data == "admin_manage_apps":
        show_app_list(chat_id, msg_id)
    elif call.data == "add_app":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="admin_manage_apps", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 📦 <b>ADD APP</b> 》\n━━━━━━━━━━━━━━━\n<b>Send app name:</b>\n\n<b>Example:</b> TELEGRAM", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_add_app, msg_id)
    elif call.data.startswith("del_app|"):
        app_name = call.data.split("|")[1]
        apps = data.get("apps", [])
        if app_name in apps:
            apps.remove(app_name)
            save_data(data)
        show_app_list(chat_id, msg_id)
    elif call.data == "admin_manage_admins":
        show_manage_admins(chat_id, msg_id)
    elif call.data == "add_new_admin":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="admin_manage_admins", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 👮 <b>ADD ADMIN</b> 》\n━━━━━━━━━━━━━━━\n<b>SEND USER ID:</b>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_add_admin, msg_id)
    elif call.data.startswith("deladm_"):
        adm_id = int(call.data.split("_")[1])
        if adm_id in data.get("extra_admins", []):
            data["extra_admins"].remove(adm_id); save_data(data)
        show_manage_admins(chat_id, msg_id)
    elif call.data in ["sys_cool", "sys_num_req", "sys_sup"]:
        action_map = {
            "sys_cool": ("COOLDOWN (Seconds)", "seconds"),
            "sys_num_req": ("NUMBER PER REQUEST", "count"),
            "sys_sup": ("SUPPORT LINK", "link")
        }
        title, hint = action_map[call.data]
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="admin_system", style="success"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 ⚙️ {title} 》\n━━━━━━━━━━━━━━━\nSEND NEW {hint.upper()}:", markup)
        bot.register_next_step_handler_by_chat_id(chat_id, process_system_setting, call.data, msg_id)
    elif call.data == "refresh_traffic":
        show_traffic_info(chat_id)
    elif call.data == "back_to_user_services":
        if str(chat_id) in active_polls: active_polls[str(chat_id)] = False
        show_user_services(chat_id)
    elif call.data.startswith("usr_app|"): show_user_countries(chat_id, call.data.split("|")[1], msg_id)
    elif call.data.startswith("usr_cnt|"):
        parts = call.data.split("|")
        app_name, country_key = parts[1], parts[2]
        fetch_number_logic(chat_id, app_name, country_key, msg_id)

    elif call.data.startswith("chg_local|"):
        parts = call.data.split("|")
        app_name, country_key = parts[1], parts[2]
        if str(chat_id) in active_polls: active_polls[str(chat_id)] = False
        fetch_number_logic(chat_id, app_name, country_key, msg_id)




    # Admin Groups
    elif call.data == "admin_group_settings": safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>GROUP SETTINGS</b> 》", get_group_settings_menu(), msg_id)
    elif call.data == "set_main_otp_link":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="admin_group_settings", style="success"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>SET OTP LINK</b> 》\n━━━━━━━━━━━━━━━\n<b>SEND OTP GROUP URL:</b>\n\n<b>Public:</b> <code>https://t.me/groupname</code>\n<b>Private:</b> <code>https://t.me/+abcdef</code>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_main_otp_link, msg_id)
    elif call.data == "del_main_otp_link":
        data["main_otp_link"] = "https://t.me/"; save_data(data)
        bot.answer_callback_query(call.id, "✅ LINK REMOVED!", show_alert=True)
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>GROUP SETTINGS</b> 》", get_group_settings_menu(), msg_id)
    elif call.data == "add_fwd_group":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="admin_group_settings", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 ➕ <b>ADD GROUP</b> 》\n━━━━━━━━━━━━━━━\n<b>SEND GROUP CHAT ID:</b>\n\n<b>Works for both public & private groups!</b>\n<b>Example:</b> <code>-1001234567890</code>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, step1_add_fwd_group, msg_id)
    elif call.data.startswith("editgrp_"): show_edit_group_menu(chat_id, call.data.split("_")[1], msg_id)
    elif call.data.startswith("addgrpbtn_"):
        grp_id = call.data.split("_")[1]
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data=f"editgrp_{grp_id}", style="success"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 📝 BUTTON NAME 》\n━━━━━━━━━━━━━━━\nSEND NAME:", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, step_addgrpbtn_name, grp_id, msg_id)
    elif call.data.startswith("delgrpbtn_"):
        parts = call.data.split("_"); grp_id, btn_idx = parts[1], int(parts[2])
        for g in data.get("forward_groups", []):
            if str(g['chat_id']) == str(grp_id):
                if 0 <= btn_idx < len(g.get("buttons", [])): g["buttons"].pop(btn_idx)
                break
        save_data(data); show_edit_group_menu(chat_id, grp_id, msg_id)
    elif call.data.startswith("delfwd_"):
        grp_id = call.data.split("_")[1]
        data["forward_groups"] = [g for g in data.get("forward_groups", []) if str(g['chat_id']) != grp_id]
        save_data(data)
        bot.answer_callback_query(call.id, "✅ GROUP DELETED!", show_alert=True)
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>GROUP SETTINGS</b> 》", get_group_settings_menu(), msg_id)

    # Force Join
    elif call.data == "admin_force_join": safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》", get_force_join_menu(), msg_id)
    elif call.data == "toggle_force_join":
        data["force_join_enabled"] = not data.get("force_join_enabled", False); save_data(data)
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》", get_force_join_menu(), msg_id)
    elif call.data == "add_fjc":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="admin_force_join", style="success"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>NEW CHANNEL/GROUP</b> 》\n━━━━━━━━━━━━━━━\n<b>SEND CHANNEL/GROUP LINK OR CHAT ID:</b>\n\n<b>Public:</b> <code>https://t.me/yourchannel</code>\n<b>Private:</b> <code>https://t.me/+abcdef</code>\n<b>Chat ID:</b> <code>-1001234567890</code>\n\n⚠️ <b>Bot must be admin of channel/group!</b>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_set_force_join_link, msg_id)
    elif call.data.startswith("delfjc_"):
        idx = int(call.data.split("_")[1])
        if 0 <= idx < len(data.get("force_join_channels", [])):
            data["force_join_channels"].pop(idx); save_data(data)
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》", get_force_join_menu(), msg_id)

    # Watermark & Broadcast
    elif call.data == "admin_set_watermark":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="back_to_admin", style="primary"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 💎 <b>WATERMARK</b> 》\n━━━━━━━━━━━━━━━\n<b>CURRENT:</b> {data.get('watermark', 'DXA UNIVERSE')}\n\n<b>SEND NEW:</b>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_set_watermark, msg_id)
    elif call.data == "admin_broadcast":
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="back_to_admin", style="danger"))
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 📢 <b>BROADCAST</b> 》\n━━━━━━━━━━━━━━━\n<b>SEND MESSAGE:</b>", markup, msg_id)
        bot.register_next_step_handler_by_chat_id(chat_id, process_broadcast, msg_id)
    else:
        pass  # Unknown callback - ignore silently

# ==================== PROCESSING FUNCTIONS ====================

def process_2fa_code(message):
    if message.text == '/cancel': show_2fa_menu_display(message.chat.id); return
    
    raw_key = message.text.upper()
    secret_key = re.sub(r'[^A-Z2-7=]', '', raw_key)
    
    if len(secret_key) < 8:
        safe_send(message.chat.id, "━━━━━━━━━━━━━━━\n《 ❌ <b>INVALID KEY</b> 》\n━━━━━━━━━━━━━━━\n<b>Please send a valid 2FA secret key!</b>\n\n<b>Example: JBSWY3DPEHPK3PXP</b>")
        return
    if message.chat.id not in user_states: user_states[message.chat.id] = {}
    user_states[message.chat.id]['2fa_key'] = secret_key
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    process_2fa_refresh_logic(message.chat.id, secret_key)

def process_2fa_refresh_logic(chat_id, secret_key):
    try:
        padding = len(secret_key) % 8
        if padding != 0:
            secret_key += '=' * (8 - padding)

        totp = pyotp.TOTP(secret_key)
        code = totp.now()
        remaining = 30 - (int(time.time()) % 30)
        tfa_data = load_data()
        tfa_watermark = tfa_data.get("watermark", "DXA UNIVERSE")
        text = (
            f"━━━━━━━━━━━━━━━\n"
            f"《 🔐 <b>2FA CODE</b> 》\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🔐 <b>CODE:</b> <code>{code}</code>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⏰ EXPIRES IN: <b>{remaining}s</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🚀 <b>POWERED BY {html.escape(tfa_watermark)}</b>"
        )
        markup = InlineKeyboardMarkup(row_width=1)
        
        markup.add(ibtn(f"📋 COPY: {code}", copy_text_str=code, style="success"))
        
        markup.add(ibtn("🔄 REFRESH CODE", callback_data="2fa_refresh", style="primary"),
                   ibtn("🆕 NEW CODE", callback_data="2fa_generate", style="danger"),
                   ibtn("🔙 BACK", callback_data="2fa_back", style="success"))
        safe_edit(chat_id, text, markup)
    except Exception as e:
        safe_edit(chat_id, "━━━━━━━━━━━━━━━\n《 ❌ <b>ERROR</b> 》\n━━━━━━━━━━━━━━━\n<b>INVALID 2FA KEY!</b>")

def process_set_force_join_link(message, msg_id):
    if message.text == '/cancel':
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》", get_force_join_menu()); return
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    raw_input = message.text.strip()
    
    if raw_input.lstrip('-').isdigit():
        numeric_id = int(raw_input)
        try:
            chat_info = bot.get_chat(numeric_id)
            bot_member = bot.get_chat_member(numeric_id, bot.get_me().id)
            if bot_member.status not in ['administrator', 'creator']:
                safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n❌ <b>Bot is not admin in this channel/group!</b>\nMake the bot admin first, then try again.", get_force_join_menu())
                return
            chat_type = detect_chat_type(chat_info)
            chat_title = chat_info.title if chat_info.title else "Unknown"
            try:
                invite_link = chat_info.invite_link
                if not invite_link:
                    invite_link = bot.export_chat_invite_link(numeric_id)
            except:
                invite_link = ""
            channel_entry = {"link": invite_link, "chat_id": numeric_id, "chat_type": chat_type, "title": chat_title}
            data = load_data()
            data.setdefault("force_join_channels", []).append(channel_entry); save_data(data)
            type_label = "GROUP" if chat_type == "group" else "CHANNEL"
            safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n✅ <b>{type_label} ADDED!</b>\n📝 <b>Name:</b> {html.escape(chat_title)}\n🆔 <b>Type:</b> {type_label}", get_force_join_menu())
            return
        except:
            safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n❌ <b>Cannot access this chat ID!</b>\nMake sure the bot is admin and the ID is correct.", get_force_join_menu())
            return
    
    link = format_url(raw_input)
    
    if is_private_invite_link(link):
        user_states[message.chat.id] = {'pending_fjc_link': link}
        markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data="admin_force_join", style="success"))
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 🔒 <b>PRIVATE CHANNEL/GROUP</b> 》\n━━━━━━━━━━━━━━━\n✅ <b>Link saved!</b>\n\n📝 <b>Now send the numeric Chat ID:</b>\n<b>Example:</b> <code>-1001234567890</code>\n\n💡 <b>Tip:</b> Forward a message from the channel to @userinfobot or @RawDataBot to get the Chat ID.", markup)
        bot.register_next_step_handler_by_chat_id(message.chat.id, process_force_join_private_chatid, msg_id)
        return
    
    chat_identifier = extract_channel_identifier(link)
    if chat_identifier is None:
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n❌ <b>INVALID LINK!</b>\n\nSend a valid link or Chat ID.", get_force_join_menu())
        return
    try:
        chat_info = bot.get_chat(chat_identifier)
        bot_member = bot.get_chat_member(chat_identifier, bot.get_me().id)
        if bot_member.status not in ['administrator', 'creator']:
            safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n❌ <b>Bot is not admin in this channel/group!</b>\nMake the bot admin first, then try again.", get_force_join_menu())
            return
    except:
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n❌ <b>Cannot access channel/group!</b>\nMake sure the bot is admin and the link is correct.", get_force_join_menu())
        return
    chat_type = detect_chat_type(chat_info)
    chat_title = chat_info.title if chat_info.title else "Unknown"
    channel_entry = {"link": link, "chat_id": chat_identifier, "chat_type": chat_type, "title": chat_title}
    data = load_data()
    data.setdefault("force_join_channels", []).append(channel_entry); save_data(data)
    type_label = "GROUP" if chat_type == "group" else "CHANNEL"
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n✅ <b>{type_label} ADDED!</b>\n📝 <b>Name:</b> {html.escape(chat_title)}\n🆔 <b>Type:</b> {type_label}", get_force_join_menu())

def process_force_join_private_chatid(message, msg_id):
    if message.text == '/cancel':
        if message.chat.id in user_states: user_states.pop(message.chat.id, None)
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》", get_force_join_menu()); return
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    raw_id = message.text.strip()
    if not raw_id.lstrip('-').isdigit():
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n❌ <b>INVALID CHAT ID!</b>\nPlease send a numeric Chat ID like <code>-1001234567890</code>", get_force_join_menu())
        if message.chat.id in user_states: user_states.pop(message.chat.id, None)
        return
    numeric_id = int(raw_id)
    saved_link = user_states.get(message.chat.id, {}).get('pending_fjc_link', '')
    try:
        chat_info = bot.get_chat(numeric_id)
        bot_member = bot.get_chat_member(numeric_id, bot.get_me().id)
        if bot_member.status not in ['administrator', 'creator']:
            safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n❌ <b>Bot is not admin in this channel/group!</b>\nMake the bot admin first, then try again.", get_force_join_menu())
            if message.chat.id in user_states: user_states.pop(message.chat.id, None)
            return
    except:
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n❌ <b>Cannot access this chat!</b>\nMake sure the bot is admin and the ID is correct.", get_force_join_menu())
        if message.chat.id in user_states: user_states.pop(message.chat.id, None)
        return
    chat_type = detect_chat_type(chat_info)
    chat_title = chat_info.title if chat_info.title else "Unknown"
    channel_entry = {"link": saved_link, "chat_id": numeric_id, "chat_type": chat_type, "title": chat_title}
    data = load_data()
    data.setdefault("force_join_channels", []).append(channel_entry); save_data(data)
    if message.chat.id in user_states: user_states.pop(message.chat.id, None)
    type_label = "GROUP" if chat_type == "group" else "CHANNEL"
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 📣 <b>FORCE JOIN</b> 》\n━━━━━━━━━━━━━━━\n✅ <b>PRIVATE {type_label} ADDED!</b>\n📝 <b>Name:</b> {html.escape(chat_title)}\n🆔 <b>Type:</b> {type_label}", get_force_join_menu())

def process_add_panel_step1(message, msg_id):
    if message.text == '/cancel': return show_panel_list(message.chat.id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    panel_name = message.text.strip()
    
    state = user_states.get(message.chat.id, {})
    state["add_panel_name"] = panel_name
    user_states[message.chat.id] = state
    
    markup = InlineKeyboardMarkup().add(ibtn("🔙 Back to Panels", callback_data="admin_manage_panels", style="primary"))
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n✅ <b>Name:</b> {html.escape(panel_name)}\n━━━━━━━━━━━━━━━\n<b>Step 2/3: Send the Panel API URL:</b>\n\n<b>Example:</b> https://yourpanel.com/api/sms", markup)
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_add_panel_step2, msg_id)

def process_add_panel_step2(message, msg_id):
    if message.text == '/cancel': return show_panel_list(message.chat.id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    api_url = message.text.strip()
    state = user_states.get(message.chat.id, {})
    state["add_panel_url"] = api_url
    user_states[message.chat.id] = state
    markup = InlineKeyboardMarkup().add(ibtn("🔙 Back to Panels", callback_data="admin_manage_panels", style="primary"))
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n✅ <b>API URL:</b> {html.escape(api_url)}\n━━━━━━━━━━━━━━━\n<b>Step 3/3: Send the API Token:</b>", markup)
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_add_panel_step3, msg_id)

def process_add_panel_step3(message, msg_id):
    if message.text == '/cancel': return show_panel_list(message.chat.id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    api_key = message.text.strip()
    state = user_states.get(message.chat.id, {})
    panel_name = state.get("add_panel_name", "Panel")
    api_url = state.get("add_panel_url", "")
    fetch_type = state.get("new_panel_fetch_type", "manual")
    
    # Auto-configure: detect format, clean URL, test API
    config = _auto_configure_panel(api_url, api_key)
    clean_url = config["api_url"]
    detected_fmt = config["api_format"]
    fmt_label = config["fmt_label"]
    
    data = load_data()
    panel_id = "p_" + str(uuid.uuid4())[:8]
    panel_num_id = len(data.get("panels", {})) + 1
    data.setdefault("panels", {})[panel_id] = {
        "name": panel_name,
        "type": "api",
        "fetch_type": fetch_type,
        "status": "active",
        "api_url": clean_url,
        "api_key": api_key,
        "api_format": detected_fmt,
        "login_url": "",
        "login_user": "",
        "login_pass": "",
        "ranges": {}
    }
    save_data(data)
    user_states.pop(message.chat.id, None)
    
    # Show auto-configuration result
    test_icon = "✅" if config["test_ok"] else "⚠️"
    url_changed = f"\n🔄 URL Fixed: <code>{html.escape(clean_url)}</code>" if clean_url != api_url.rstrip("/") else ""
    auto_note = ""
    if fetch_type == "auto":
        auto_note = "\n\n📌 <b>Next:</b> Add Ranges (Country + Service + Range Code) to start fetching numbers from API."
    safe_send(message.chat.id, f"━━━━━━━━━━━━━━━\n🔧 Panel <b>{html.escape(panel_name)}</b> created!\nType: {fetch_type.upper()}\nFormat: {fmt_label}{url_changed}\n{test_icon} {config['test_msg']}\nID: {panel_num_id}{auto_note}\n━━━━━━━━━━━━━━━")
    show_panel_detail(message.chat.id, panel_id)

def process_set_api_url(message, panel_id, msg_id):
    if message.text == '/cancel': return show_panel_detail(message.chat.id, panel_id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    api_url = message.text.strip()
    user_states[message.chat.id] = {"set_api_panel": panel_id, "set_api_url": api_url}
    markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data=f"panel_view|{panel_id}", style="primary"))
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n✅ <b>API URL:</b> {html.escape(api_url)}\n━━━━━━━━━━━━━━━\n<b>Step 2/2: Send the API Token:</b>", markup)
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_set_api_key, panel_id, msg_id)

def process_set_api_key(message, panel_id, msg_id):
    if message.text == '/cancel': return show_panel_detail(message.chat.id, panel_id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    state = user_states.get(message.chat.id, {})
    api_url = state.get("set_api_url", "")
    api_key = message.text.strip()
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if panel:
        # Auto-configure: detect format, clean URL, test API
        config = _auto_configure_panel(api_url, api_key)
        panel["api_url"] = config["api_url"]
        panel["api_key"] = api_key
        panel["api_format"] = config["api_format"]
        save_data(data)
        test_icon = "✅" if config["test_ok"] else "⚠️"
        url_note = f"\n🔄 URL Fixed: <code>{html.escape(config['api_url'])}</code>" if config["api_url"] != api_url.rstrip("/") else ""
        safe_send(message.chat.id, f"━━━━━━━━━━━━━━━\n✅ <b>API credentials saved!</b>\nFormat: {config['fmt_label']}{url_note}\n{test_icon} {config['test_msg']}\n━━━━━━━━━━━━━━━")
    user_states.pop(message.chat.id, None)
    show_panel_detail(message.chat.id, panel_id)

def process_set_login_url(message, panel_id, msg_id):
    if message.text == '/cancel': return show_panel_detail(message.chat.id, panel_id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    login_url = message.text.strip()
    user_states[message.chat.id] = {"set_login_panel": panel_id, "set_login_url": login_url}
    markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data=f"panel_view|{panel_id}", style="primary"))
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n✅ <b>Login URL:</b> {html.escape(login_url)}\n━━━━━━━━━━━━━━━\n<b>Step 2/2: Send username:password</b>", markup)
    bot.register_next_step_handler_by_chat_id(message.chat.id, process_set_login_creds, panel_id, msg_id)

def process_set_login_creds(message, panel_id, msg_id):
    if message.text == '/cancel': return show_panel_detail(message.chat.id, panel_id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    state = user_states.get(message.chat.id, {})
    login_url = state.get("set_login_url", "")
    creds = message.text.strip()
    parts = creds.split(":", 1)
    username = parts[0] if parts else ""
    password = parts[1] if len(parts) > 1 else ""
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if panel:
        panel["login_url"] = login_url
        panel["login_user"] = username
        panel["login_pass"] = password
        save_data(data)
        login_sessions.pop(panel_id, None)
        sess = do_login_session(panel)
        if sess:
            login_sessions[panel_id] = sess
            token_info = "Token" if sess.get("token") else "Cookie"
            safe_send(message.chat.id, f"━━━━━━━━━━━━━━━\n✅ <b>Login credentials saved!</b>\n🔑 Auth: {token_info}\n━━━━━━━━━━━━━━━")
        else:
            safe_send(message.chat.id, f"━━━━━━━━━━━━━━━\n⚠️ <b>Credentials saved but login test failed!</b>\n<i>Check URL/creds</i>\n━━━━━━━━━━━━━━━")
    user_states.pop(message.chat.id, None)
    show_panel_detail(message.chat.id, panel_id)

def process_rename_panel(message, panel_id, msg_id):
    if message.text == '/cancel': return show_panel_detail(message.chat.id, panel_id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    data = load_data()
    panel = data.get("panels", {}).get(panel_id)
    if panel:
        panel["name"] = message.text.strip()
        save_data(data)
    show_panel_detail(message.chat.id, panel_id)

## OLD STEP HANDLERS REMOVED - Replaced by state-machine flow:
## _flow_add_range_country, _flow_add_range_service, _flow_add_range_cc
## These are handled by handle_active_flow message handler

def process_add_numbers_to_range(message, panel_id, rng_id, msg_id):
    chat_id = message.chat.id
    if message.text == '/cancel':
        return show_range_detail(chat_id, panel_id, rng_id, msg_id)
    
    numbers = []
    
    if message.document:
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            text_content = downloaded.decode('utf-8', errors='ignore')
            for line in text_content.strip().split('\n'):
                for num in line.strip().split(','):
                    cleaned = re.sub(r'[^0-9]', '', num.strip())
                    if len(cleaned) >= 7:
                        numbers.append(cleaned)
        except:
            pass
    elif message.text:
        raw = message.text.strip()
        for line in raw.split('\n'):
            for num in line.strip().split(','):
                cleaned = re.sub(r'[^0-9]', '', num.strip())
                if len(cleaned) >= 7:
                    numbers.append(cleaned)
    
    try: bot.delete_message(chat_id, message.message_id)
    except: pass
    
    if numbers:
        data = load_data()
        panel = data.get("panels", {}).get(panel_id)
        if panel:
            rng = panel.get("ranges", {}).get(rng_id)
            if rng:
                existing = set(rng.get("numbers", []))
                new_nums = [n for n in numbers if n not in existing]
                rng["numbers"].extend(new_nums)
                save_data(data)
                total_now = len(rng["numbers"])
                safe_send(chat_id, f"┌─────────────────┐\n│ ✅ <b>Numbers Added!</b>\n├─────────────────┤\n│ ➕ Added: <code>{len(new_nums)}</code>\n│ ⏭️ Skipped (dupe): <code>{len(numbers) - len(new_nums)}</code>\n│ 📊 Total in range: <code>{total_now}</code>\n└─────────────────┘")
    else:
        safe_send(chat_id, "━━━━━━━━━━━━━━━\n❌ <b>No valid numbers found!</b>\n━━━━━━━━━━━━━━━")
    
    show_range_detail(chat_id, panel_id, rng_id)

def process_add_app(message, msg_id):
    if message.text == '/cancel': return show_app_list(message.chat.id, msg_id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    data = load_data()
    app_name = message.text.strip().upper()
    apps = data.setdefault("apps", DEFAULT_APPS[:])
    if app_name not in apps:
        apps.append(app_name)
        save_data(data)
    show_app_list(message.chat.id)

def step1_add_fwd_group(message, msg_id):
    if message.text == '/cancel':
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>GROUP SETTINGS</b> 》", get_group_settings_menu()); return
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    data = load_data()
    data.setdefault("forward_groups", []).append({"chat_id": message.text.strip(), "buttons": []}); save_data(data)
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>GROUP SETTINGS</b> 》\n━━━━━━━━━━━━━━━\n✅ <b>GROUP ADDED!</b>", get_group_settings_menu())

def step_addgrpbtn_name(message, grp_id, msg_id):
    if message.text == '/cancel': show_edit_group_menu(message.chat.id, grp_id, msg_id); return
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    user_states[message.chat.id] = {'grp_id': grp_id, 'btn_name': message.text.strip()}
    markup = InlineKeyboardMarkup().add(ibtn("🔙 CANCEL", callback_data=f"editgrp_{grp_id}", style="danger"))
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>BUTTON URL</b> 》\n━━━━━━━━━━━━━━━\n<b>SEND URL:</b>", markup)
    bot.register_next_step_handler_by_chat_id(message.chat.id, step_addgrpbtn_url, msg_id)

def step_addgrpbtn_url(message, msg_id):
    if message.text == '/cancel':
        grp_id = user_states.get(message.chat.id, {}).get('grp_id')
        if grp_id: show_edit_group_menu(message.chat.id, grp_id, msg_id); return
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    state = user_states.get(message.chat.id, {})
    grp_id = state.get('grp_id'); btn_name = state.get('btn_name')
    btn_url = format_url(message.text.strip())
    data = load_data()
    for grp in data.get("forward_groups", []):
        if str(grp['chat_id']) == str(grp_id):
            grp.setdefault("buttons", []).append({"name": btn_name, "url": btn_url}); break
    save_data(data)
    show_edit_group_menu(message.chat.id, grp_id)

def process_main_otp_link(message, msg_id):
    if message.text == '/cancel':
        safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>GROUP SETTINGS</b> 》", get_group_settings_menu()); return
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    data = load_data()
    data["main_otp_link"] = format_url(message.text.strip()); save_data(data)
    safe_edit(message.chat.id, f"━━━━━━━━━━━━━━━\n《 🔗 <b>GROUP SETTINGS</b> 》\n━━━━━━━━━━━━━━━\n✅ <b>LINK UPDATED!</b>", get_group_settings_menu())

def process_set_watermark(message, msg_id):
    if message.text == '/cancel': return show_admin_panel(message.chat.id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    data = load_data()
    data["watermark"] = message.text.strip(); save_data(data)
    show_admin_panel(message.chat.id)

def run_broadcast(chat_id, original_message, msg_id):
    data = load_data()
    users = data.get("users", [])
    success, failed = 0, 0
    for u in users:
        try:
            bot.copy_message(chat_id=u, from_chat_id=chat_id, message_id=original_message.message_id)
            success += 1; time.sleep(0.05)
        except: failed += 1
    markup = InlineKeyboardMarkup().add(ibtn("🔙 BACK", callback_data="back_to_admin", style="success"))
    safe_send(chat_id, f"━━━━━━━━━━━━━━━\n《 📢 BROADCAST DONE 》\n━━━━━━━━━━━━━━━\n✅ SENT: {success}\n❌ FAILED: {failed}", markup)

def process_broadcast(message, msg_id):
    if message.text == '/cancel': return show_admin_panel(message.chat.id, msg_id)
    safe_send(message.chat.id, f"━━━━━━━━━━━━━━━\n《 🔄 BROADCASTING... 》")
    threading.Thread(target=run_broadcast, args=(message.chat.id, message, msg_id)).start()

def process_system_setting(message, action, msg_id):
    if message.text == '/cancel': return show_admin_system(message.chat.id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    data = load_data()
    val = message.text.strip()
    
    try:
        if action == "sys_cool": data["settings"]["cooldown"] = int(val)
        elif action == "sys_num_req": data["settings"]["num_per_request"] = int(val)
        elif action == "sys_sup": data["settings"]["support_link"] = format_url(val)
    except ValueError:
        safe_edit(message.chat.id, "<b>━━━━━━━━━━━━━━━\n《 ⚙️ SYSTEM SETTINGS 》\n━━━━━━━━━━━━━━━\n❌ INVALID FORMAT! MUST BE A NUMBER.</b>")
        return show_admin_system(message.chat.id)
        
    save_data(data)
    show_admin_system(message.chat.id)

def show_ban_unban_menu(chat_id, message_id=None):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(ibtn("🔨 BAN", callback_data="uv_ban_do", style="danger"),
               ibtn("♻️ UNBAN", callback_data="uv_unban_list", style="success"))
    markup.add(ibtn("🔙 BACK", callback_data="admin_user_view", style="primary"))
    safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 🚫 BAN / UNBAN MENU 》\n━━━━━━━━━━━━━━━\nCHOOSE AN ACTION:", markup, message_id)

def show_unban_list(chat_id, message_id=None):
    data = load_data()
    banned = data.get("banned_users", [])
    markup = InlineKeyboardMarkup(row_width=1)
    if not banned:
        safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 ♻️ <b>UNBAN USER</b> 》\n━━━━━━━━━━━━━━━\n<b>✅ NO BANNED USERS FOUND!</b>", InlineKeyboardMarkup().add(ibtn("🔙 BACK", callback_data="uv_ban_menu", style="success")), message_id)
        return
    for uid in banned:
        markup.add(ibtn(f"♻️ UNBAN: {uid}", callback_data=f"unban_{uid}", style="success"))
    markup.add(ibtn("🔙 BACK", callback_data="uv_ban_menu", style="primary"))
    safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 ♻️ <b>UNBAN LIST</b> 》\n━━━━━━━━━━━━━━━\n<b>SELECT A USER TO UNBAN:</b>", markup, message_id)

def process_do_ban(message, msg_id):
    if message.text == '/cancel': return show_ban_unban_menu(message.chat.id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    try:
        uid = int(message.text.strip())
        data = load_data()
        if uid not in data.get("banned_users", []):
            data.setdefault("banned_users", []).append(uid)
            save_data(data)
        show_ban_unban_menu(message.chat.id)
    except:
        show_ban_unban_menu(message.chat.id)

def process_user_profile(message, msg_id):
    if message.text == '/cancel': return show_user_view(message.chat.id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    uid = message.text.strip()
    data = load_data()
    
    otps = data.get("otp_counts", {}).get(uid, 0)
    
    uid_check = int(uid) if uid.isdigit() else uid
    is_banned = "🔴 BANNED" if uid_check in data.get("banned_users", []) else "✅ ACTIVE"
    
    text = (
        f"━━━━━━━━━━━━━━━\n"
        f"《 👤 <b>USER PROFILE</b> 》\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🆔 <b>ID:</b> <code>{uid}</code>\n"
        f"🔐 <b>Total OTPs:</b> {otps}\n"
        f"⚠️ <b>Status:</b> {is_banned}\n"
        f"━━━━━━━━━━━━━━━"
    )
    markup = InlineKeyboardMarkup().add(ibtn("🔙 BACK", callback_data="admin_user_view", style="success"))
    safe_edit(message.chat.id, text, markup)



def show_manage_admins(chat_id, message_id=None):
    data = load_data()
    admins = data.get("extra_admins", [])
    markup = InlineKeyboardMarkup(row_width=1)
    
    for adm in admins:
        markup.add(ibtn(f"❌ REMOVE: {adm}", callback_data=f"deladm_{adm}", style="danger"))
        
    markup.add(ibtn("➕ ADD ADMIN", callback_data="add_new_admin", style="success"))
    markup.add(ibtn("🔙 BACK", callback_data="back_to_admin", style="primary"))
    
    safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 👮 <b>MANAGE ADMINS</b> 》\n━━━━━━━━━━━━━━━\n<b>TOTAL EXTRA ADMINS:</b> {len(admins)}", markup, message_id)

def process_add_admin(message, msg_id):
    if message.text == '/cancel': return show_manage_admins(message.chat.id)
    try: bot.delete_message(message.chat.id, message.message_id)
    except: pass
    try:
        adm_id = int(message.text.strip())
        data = load_data()
        if adm_id not in data.get("extra_admins", []):
            data.setdefault("extra_admins", []).append(adm_id)
            save_data(data)
    except: pass
    show_manage_admins(message.chat.id)

# ==================== CORE OTP - LOCAL NUMBER SYSTEM ====================

COUNTRY_ALIASES = {
    "ivory coast": "cote d'ivoire", "cote d'ivoire": "ivory coast",
    "uae": "united arab emirates", "united arab emirates": "uae",
    "uk": "united kingdom", "united kingdom": "uk",
    "usa": "united states", "united states": "usa", "us": "united states",
    "south korea": "korea", "korea": "south korea",
    "czech republic": "czechia", "czechia": "czech republic",
    "drc": "congo", "congo": "drc",
}

def _get_expected_dial_code(country_name):
    """Get the expected dialing code for a country name."""
    name = country_name.lower().strip()
    for code, cname in PHONE_TO_COUNTRY.items():
        if cname.lower() == name:
            return code
    alias = COUNTRY_ALIASES.get(name, "")
    if alias:
        for code, cname in PHONE_TO_COUNTRY.items():
            if cname.lower() == alias.lower():
                return code
    return ""

def _validate_country_match(number, expected_country_name):
    """Check if phone number matches expected country by dialing code prefix."""
    raw = str(number).replace('+', '').strip()
    if not raw or not expected_country_name:
        return True
    
    # Get expected dialing code
    expected_dial = _get_expected_dial_code(expected_country_name)
    if not expected_dial:
        return True  # Can't validate - unknown country
    
    # Direct prefix check - most reliable
    if raw.startswith(expected_dial):
        return True
    
    # Check aliases
    alias = COUNTRY_ALIASES.get(expected_country_name.lower().strip(), "")
    if alias:
        alias_dial = _get_expected_dial_code(alias)
        if alias_dial and raw.startswith(alias_dial):
            return True
    
    return False

def _fetch_auto_api(panel, panel_id, rng_id, service_code, country_key, numbers_found, req_limit, expected_country=""):
    api_url = panel.get("api_url", "").rstrip("/")
    api_key = panel.get("api_key", "")
    p_type = panel.get("type", "api")
    fmt_name = panel.get("api_format", detect_panel_format(api_url, api_key))
    fmt = PANEL_FORMATS.get(fmt_name, PANEL_FORMATS["standard"])
    http_method = fmt.get("http_method", "GET").upper()
    sess = None
    
    headers = {}
    if p_type == "login":
        sess = get_login_session(panel_id)
        if sess and sess.get("token"):
            headers = {'Authorization': f'Bearer {sess["token"]}'}
        elif sess and sess.get("cookies"):
            headers = {}
        else:
            return numbers_found
    else:
        headers = get_api_headers(panel)
    
    needed = req_limit - len(numbers_found)
    if needed <= 0:
        return numbers_found

    if fmt_name == "ins_agent":
        fetch_endpoint = build_api_url(panel, "get_number", service=service_code, country=country_key, limit=str(needed))
        if not fetch_endpoint:
            return numbers_found
        try:
            res = req_session.get(fetch_endpoint, headers=headers, timeout=15)
            if res.status_code == 200:
                res_data = res.json()
                if res_data.get("ok") and res_data.get("data"):
                    for item in res_data["data"][:needed]:
                        num = str(item.get("number", ""))
                        num_id = str(item.get("id", f"auto_{int(time.time()*1000)}"))
                        if expected_country and not _validate_country_match(num, expected_country):
                            continue
                        if num and not any(nf["number"] == num for nf in numbers_found):
                            numbers_found.append({
                                "number": num, "number_id": num_id, "panel_id": panel_id,
                                "panel_name": panel.get("name", "Auto Server"), "rng_id": rng_id,
                                "api_key": api_key, "api_url": api_url, "status": "\u23f3 WAITING",
                                "panel_type": p_type, "cli_name": item.get("cli_name", "")
                            })
                        if len(numbers_found) >= req_limit:
                            break
        except:
            pass
        return numbers_found
    
    fetch_endpoint = build_api_url(panel, "get_number", service=service_code, country=country_key)
    if not fetch_endpoint:
        fetch_endpoint = f"{api_url}/getNumber?service={service_code}&country={country_key}"
    
    max_retries = needed + 5
    wrong_count = 0
    for _ in range(max_retries):
        if len(numbers_found) >= req_limit:
            break
        if wrong_count >= 3:
            break
        try:
            if p_type == "login" and sess and sess.get("session"):
                http_sess = sess["session"]
            else:
                http_sess = req_session
            
            if http_method == "POST":
                post_body_template = fmt.get("post_body")
                if post_body_template:
                    body = copy.deepcopy(post_body_template)
                    for bk in body:
                        if isinstance(body[bk], str):
                            body[bk] = body[bk].replace("{service}", service_code).replace("{country}", country_key)
                    post_headers = dict(headers)
                    post_headers["Content-Type"] = "application/json"
                    res = http_sess.post(fetch_endpoint, headers=post_headers, json=body, timeout=15)
                else:
                    res = http_sess.post(fetch_endpoint, headers=headers, timeout=15)
            else:
                res = http_sess.get(fetch_endpoint, headers=headers, timeout=15)
            
            if res.status_code == 200:
                try:
                    res_data = res.json()
                except:
                    break
                data_wrapper = fmt.get("data_wrapper")
                if data_wrapper and data_wrapper in res_data:
                    res_data = res_data[data_wrapper]
                    if isinstance(res_data, list):
                        if len(res_data) > 0:
                            res_data = res_data[0]
                        else:
                            break
                
                parsed = parse_number_response(panel, res_data)
                if parsed["success"] and parsed["number"]:
                    num = parsed["number"]
                    if expected_country and not _validate_country_match(num, expected_country):
                        wrong_count += 1
                        continue
                    trk_id = parsed["id"] or f"auto_{int(time.time()*1000)}"
                    if not any(nf["number"] == num for nf in numbers_found):
                        numbers_found.append({
                            "number": num, "number_id": trk_id, "panel_id": panel_id,
                            "panel_name": panel.get("name", "Auto Server"), "rng_id": rng_id,
                            "api_key": api_key, "api_url": api_url, "status": "\u23f3 WAITING",
                            "panel_type": p_type
                        })
                else:
                    break
            elif res.status_code == 401 and p_type == "login":
                login_sessions.pop(panel_id, None)
                sess = get_login_session(panel_id)
                if not sess: break
            else:
                break
        except:
            break
    return numbers_found

def fetch_number_logic(chat_id, app_name, country_key, message_id):
    """Fetch numbers from either manual list or Auto API matching Server and Country."""
    data = load_data()
    main_link = format_url(data.get("main_otp_link", "https://t.me/"))
    st = data.get("settings", {})
    
    # Cooldown enforcement
    cooldown_sec = st.get("cooldown", 60)
    if chat_id != ADMIN_ID and chat_id not in data.get("extra_admins", []):
        last_req = user_cooldowns.get(chat_id, 0)
        elapsed = time.time() - last_req
        if elapsed < cooldown_sec:
            remaining = int(cooldown_sec - elapsed)
            markup = InlineKeyboardMarkup()
            markup.add(ibtn("🔙 BACK", callback_data="back_to_user_services", style="success"))
            markup.add(ibtn("❌ CLOSE", callback_data="close_menu", style="danger"))
            return safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 ⏳ <b>COOLDOWN</b> 》\n━━━━━━━━━━━━━━━\n⚠️ <b>PLEASE WAIT {remaining}s BEFORE NEXT REQUEST</b>\n\n🕐 <b>Cooldown:</b> <code>{cooldown_sec}s</code>\n━━━━━━━━━━━━━━━", markup, message_id)
    
    req_limit = st.get("num_per_request", 5)
    if req_limit <= 0:
        req_limit = 5
    
    if req_limit <= 0:
        markup = InlineKeyboardMarkup().add(ibtn("🔙 BACK", callback_data="back_to_user_services", style="success"))
        return safe_edit(chat_id, "━━━━━━━━━━━━━━━\n《 ⚠️ <b>NOT CONFIGURED</b> 》\n━━━━━━━━━━━━━━━\n<b>ADMIN HAS NOT SET NUMBER LIMIT</b>\n<b>PLEASE WAIT FOR ADMIN</b>", markup, message_id)

    loading_text = f"━━━━━━━━━━━━━━━\n《 ⏳ <b>PROCESSING</b> 》\n━━━━━━━━━━━━━━━\n🔄 <b>PLEASE WAIT...</b>\n<i>FETCHING {app_name.upper()} NUMBERS...</i>\n━━━━━━━━━━━━━━━"
    if message_id:
        try: bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=loading_text, parse_mode="HTML")
        except: pass
    else:
        try:
            msg = bot.send_message(chat_id, loading_text, parse_mode="HTML")
            message_id = msg.message_id
        except: pass

    numbers_found = []

    for panel_id, panel in data.get("panels", {}).items():
        if panel.get("status") != "active": continue
        if len(numbers_found) >= req_limit: break
        f_type = panel.get("fetch_type", "manual")
        
        range_matched = False
        for rng_id, rng in panel.get("ranges", {}).items():
            if rng.get("app", "").upper() != app_name.upper(): continue
            if rng.get("name", "").lower() != country_key.lower(): continue
            range_matched = True
            expected_cname = rng.get("name", country_key)
            
            if f_type == "manual":
                all_nums = rng.get("numbers", [])
                if not all_nums: continue
                used = rng.get("used_numbers", [])
                avail = [n for n in all_nums if n not in used]
                if not avail: rng["used_numbers"] = []; avail = list(all_nums)
                random.shuffle(avail)
                for num in avail:
                    if len(numbers_found) >= req_limit: break
                    rng.setdefault("used_numbers", []).append(num)
                    numbers_found.append({
                        "number": num, "number_id": f"{panel_id}_{rng_id}_{num}", "panel_id": panel_id,
                        "panel_name": panel.get("name", "Unknown"), "rng_id": rng_id,
                        "api_key": panel.get("api_key", ""), "api_url": panel.get("api_url", ""), "status": "\u23f3 WAITING",
                        "panel_type": panel.get("type", "api"), "is_manual": True
                    })
            
            else:
                api_country = rng.get("country_code", country_key)
                numbers_found = _fetch_auto_api(panel, panel_id, rng_id, rng.get("range_code", app_name), api_country, numbers_found, req_limit, expected_country=expected_cname)

            if len(numbers_found) >= req_limit: break
        
        if len(numbers_found) >= req_limit: break

    if numbers_found:
        save_data(data)
        user_cooldowns[chat_id] = time.time()
    else:
        markup = InlineKeyboardMarkup().add(ibtn("🔙 BACK", callback_data="back_to_user_services", style="success"))
        return safe_edit(chat_id, f"━━━━━━━━━━━━━━━\n《 ❌ <b>ERROR</b> 》\n━━━━━━━━━━━━━━━\n<b>SERVER IS OUT OF STOCK</b>\n<b>PLEASE TRY AGAIN LATER</b>", markup, message_id)

    service_info = {'service_name': app_name, 'country_name': country_key.title(), 'app_name': app_name, 'country_key': country_key}
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(ibtn(f"💬 {app_name.upper()}", callback_data="ignore", style="success"))

    num_color_cycle = ["primary", "success", "danger"]
    for num_idx, num_data in enumerate(numbers_found):
        raw_num = str(num_data['number']).replace('+', '')
        full_num = f"+{raw_num}" if not raw_num.startswith('+') else raw_num
        full_num = f"+{full_num}" if not full_num.startswith('+') else full_num
        num_data['number'] = full_num.replace('+', '')
        detected_country = get_country_from_number(raw_num)
        num_flag = get_country_flag(detected_country) if detected_country else get_country_flag(country_key.title())
        btn_text = f"📋 {num_flag} {full_num}"
        markup.add(ibtn(btn_text, copy_text_str=full_num, style=num_color_cycle[num_idx % 3]))

    markup.row(ibtn("🔄 Change Number", callback_data=f"chg_local|{app_name}|{country_key}", style="danger"), ibtn("🌍 Change Country", callback_data=f"usr_app|{app_name}", style="primary"))
    markup.add(ibtn("📨 OTP Group", url=main_link, style="primary"))
    markup.add(ibtn("🔙 Back", callback_data="back_to_user_services", style="success"))
    markup.add(ibtn("❌ Close", callback_data="close_menu", style="danger"))

    active_polls[str(chat_id)] = {"numbers": numbers_found, "service_info": service_info, "message_id": message_id, "is_custom": False}
    safe_edit(chat_id, "ㅤ", markup, message_id)

    for num_data in numbers_found:
        has_api_key = num_data.get("api_url") and num_data.get("api_key")
        has_login_panel = num_data.get("panel_id") and num_data.get("panel_type") == "login"
        has_panel_url = num_data.get("panel_id") and num_data.get("api_url")
        if has_api_key or has_login_panel or has_panel_url:
            threading.Thread(target=poll_otp_with_status, args=(chat_id, num_data, service_info)).start()

def update_number_status(chat_id, number, status_text, emoji_status):
    if str(chat_id) not in active_polls or not active_polls[str(chat_id)]: return
    poll_data = active_polls[str(chat_id)]
    numbers = poll_data.get("numbers", [])
    message_id = poll_data.get("message_id")
    service_info = poll_data.get("service_info", {})
    fresh_data = load_data()
    watermark = fresh_data.get("watermark", "DXA UNIVERSE")
    main_link = format_url(fresh_data.get("main_otp_link", "https://t.me/"))
    for num_data in numbers:
        if num_data["number"] == number:
            num_data["status"] = f"{emoji_status} {status_text}"; break
    
    srv_name_upper = service_info.get('service_name', '').upper()
    text = "ㅤ"
    
    markup = InlineKeyboardMarkup(row_width=1)
    
    markup.add(ibtn(f"💬 {srv_name_upper}", callback_data="ignore", style="success"))
    
    configured_flag_status = get_country_flag(service_info.get('country_name', ''))
    
    num_color_cycle = ["primary", "success", "danger"]
    for num_idx, num_data in enumerate(numbers):
        raw_num = str(num_data['number']).replace('+', '')
        if not raw_num.startswith('+'):
            raw_num = f"+{raw_num}"
        
        btn_text = f"📋 {configured_flag_status} {raw_num}"
        markup.add(ibtn(btn_text, copy_text_str=raw_num, style=num_color_cycle[num_idx % 3]))
    
    if service_info.get('country_key') and service_info.get('app_name'):
        markup.row(
            ibtn("🔄 Change Number", callback_data=f"chg_local|{service_info.get('app_name', '')}|{service_info.get('country_key', '')}", style="danger"),
            ibtn("🌍 Change Country", callback_data=f"usr_app|{service_info.get('app_name', '')}", style="primary")
        )
    else:
        markup.add(ibtn("🔄 Change Number", callback_data="back_to_user_services", style="danger"))
        
    markup.add(ibtn("📨 OTP Group", url=main_link, style="primary"))
    markup.add(ibtn("🔙 Back", callback_data="back_to_user_services", style="success"))
    markup.add(ibtn("❌ Close", callback_data="close_menu", style="danger"))
    
    try:
        clean_text = clean_html_tags(text)
        bot.edit_message_text(clean_text, chat_id=chat_id, message_id=message_id, parse_mode="HTML", reply_markup=markup)
    except: pass

def _poll_manual_login_panel(panel, panel_id, phone_number, sess, headers, fmt_name):
    """Poll a login-based panel for OTP by searching latest messages for matching phone number."""
    raw_url = panel.get("api_url", "") or panel.get("login_url", "")
    base_url = _get_api_base(raw_url, fmt_name)
    
    clean_phone = str(phone_number).replace("+", "").strip()
    # Try multiple common ints-panel endpoints to find SMS for this number
    endpoints_to_try = [
        f"{base_url}/api/getLatestSms",
        f"{base_url}/api/getSms?number={clean_phone}",
        f"{base_url}/api/getStatus?number={clean_phone}",
        f"{base_url}/api/getMessages?number={clean_phone}",
        f"{base_url}/api/getActiveOrders",
        f"{base_url}/api/getStatus?id={clean_phone}",
        f"{base_url}/sms/latest",
    ]
    
    http_sess = sess.get("session") if sess and sess.get("session") else req_session
    
    for endpoint in endpoints_to_try:
        try:
            res = http_sess.get(endpoint, headers=headers, timeout=10)
            if res.status_code != 200:
                continue
            try:
                data = res.json()
            except:
                continue
            
            # Handle different response shapes
            messages = []
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict):
                # Check for status=OK with code/sms (direct match by number)
                status_val = str(data.get("status", "")).upper()
                if status_val in ("OK", "SUCCESS", "1") and (data.get("code") or data.get("sms") or data.get("otp")):
                    return {
                        "otp": str(data.get("code") or data.get("otp") or ""),
                        "sms": str(data.get("sms") or data.get("message") or data.get("message_text") or ""),
                        "service": data.get("service", "") or data.get("app_name", "") or data.get("platform", "")
                    }
                # Check for wrapped data
                for key in ["data", "messages", "orders", "items", "results"]:
                    if key in data and isinstance(data[key], list):
                        messages = data[key]
                        break
            
            # Search through messages for our phone number
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                msg_number = str(msg.get("number", "") or msg.get("phone", "") or msg.get("phoneNumber", "")).replace("+", "").strip()
                if not msg_number:
                    continue
                # Match phone number (exact or suffix/prefix match)
                if msg_number == clean_phone or clean_phone.endswith(msg_number) or msg_number.endswith(clean_phone):
                    otp = str(msg.get("code", "") or msg.get("otp", "") or msg.get("otp_code", "") or "")
                    sms_text = str(msg.get("sms", "") or msg.get("message", "") or msg.get("message_text", "") or msg.get("text", "") or "")
                    if not otp and sms_text:
                        m = re.search(r'(\d{4,8})', sms_text)
                        if m:
                            otp = m.group(1)
                    if otp:
                        return {
                            "otp": otp,
                            "sms": sms_text,
                            "service": msg.get("service", "") or msg.get("app_name", "") or msg.get("platform", "")
                        }
        except:
            continue
    return None

def poll_otp_with_status(chat_id, num_data, service_info):
    number_id = num_data["number_id"]
    phone_number = num_data["number"]
    api_key = num_data.get("api_key", "")
    api_url = num_data.get("api_url", "")
    panel_id = num_data.get("panel_id", "")
    p_type = num_data.get("panel_type", "api")
    is_manual = num_data.get("is_manual", False)
    
    data_fresh = load_data()
    panel = data_fresh.get("panels", {}).get(panel_id, {})
    
    # Override p_type from panel data if available
    if panel:
        p_type = panel.get("type", p_type)
    
    fmt_name = panel.get("api_format", detect_panel_format(api_url, api_key)) if panel else "standard"
    fmt = PANEL_FORMATS.get(fmt_name, PANEL_FORMATS["standard"])
    
    if p_type == "login":
        sess = get_login_session(panel_id)
        if not sess:
            # Try to login first
            sess = do_login_session(panel)
            if sess:
                login_sessions[panel_id] = sess
        if sess and sess.get("token"):
            headers = {'Authorization': f'Bearer {sess["token"]}'}
        else:
            headers = {}
    else:
        sess = None
        headers = get_api_headers(panel) if panel else {'X-API-Key': api_key}
    
    clean_phone = str(phone_number).replace("+", "").strip()
    
    # Build SMS endpoint
    sms_endpoint = None
    if is_manual:
        # For manual numbers, use phone-number-based polling
        if fmt_name == "lamix":
            pass  # Lamix polling is handled inline in the polling loop below
        elif fmt_name == "ins_agent":
            base = _get_api_base(api_url, "ins_agent")
            sms_endpoint = f"{base}/api/functions/agent-api/otp?number={clean_phone}&limit=5"
        # For login panels, _poll_manual_login_panel handles endpoint discovery
    else:
        sms_endpoint = build_api_url(panel, "get_sms", number_id=number_id) if panel else None
        if not sms_endpoint:
            base = _get_api_base(api_url, fmt_name)
            sms_endpoint = f"{base}/numbers/{number_id}/sms"
    
    # Track already-seen OTP IDs to avoid delivering old OTPs
    seen_otp_ids = set()
    # On first poll, record existing OTPs so we only deliver NEW ones
    first_poll = True
    
    timeout = 600
    start_time = time.time()
    original_range = service_info.get('range', '')
    
    if not service_info.get('country_name') or service_info.get('country_name') == 'Universal':
        service_info['country_name'] = get_country_from_number(phone_number)
    
    while time.time() - start_time < timeout:
        if str(chat_id) not in active_polls or not active_polls[str(chat_id)]: return
        try:
            has_otp = False
            otp_code = ""
            full_sms = ""
            app_name_from_api = service_info.get('service_name', '')
            
            # === MANUAL NUMBER POLLING ===
            if is_manual and panel:
                if fmt_name == "lamix":
                    # Lamix CRAPI: poll viewstats endpoint with number filter
                    try:
                        lamix_base = _get_api_base(api_url, "lamix")
                        lamix_token = api_key
                        _now = datetime.now()
                        _dt1 = _now.strftime("%Y-%m-%d 00:00:00")
                        _dt2 = _now.strftime("%Y-%m-%d %H:%M:%S")
                        lamix_url = f"{lamix_base}/viewstats?token={lamix_token}&num={clean_phone}&dt1={_dt1}&dt2={_dt2}&records=20"
                        res = req_session.get(lamix_url, timeout=15)
                        if res.status_code == 200:
                            resp = res.json()
                            if resp.get("status") == "success" and isinstance(resp.get("data"), list):
                                for item in resp["data"]:
                                    # Match phone number (API may return unfiltered results)
                                    item_num = str(item.get("num", "")).replace("+", "").strip()
                                    if item_num != clean_phone and not clean_phone.endswith(item_num) and not item_num.endswith(clean_phone):
                                        continue
                                    item_id = f"{item.get('dt', '')}_{item_num}_{item.get('cli', '')}"
                                    if first_poll:
                                        seen_otp_ids.add(item_id)
                                        continue
                                    if item_id and item_id not in seen_otp_ids:
                                        seen_otp_ids.add(item_id)
                                        sms_val = item.get("message", "")
                                        otp_val = ""
                                        if sms_val:
                                            # Try numeric OTP first
                                            m = re.search(r'(?:code|otp|Code|OTP|kod)\D{0,10}(\d{4,8})', sms_val, re.IGNORECASE)
                                            if m:
                                                otp_val = m.group(1)
                                            else:
                                                m = re.search(r'(\d{4,8})', sms_val)
                                                if m: otp_val = m.group(1)
                                            # Try alphanumeric code at end of message
                                            if not otp_val:
                                                m = re.search(r'([a-zA-Z0-9]{4,10})\s*$', sms_val)
                                                if m: otp_val = m.group(1)
                                        if otp_val:
                                            has_otp = True
                                            otp_code = str(otp_val)
                                            full_sms = str(sms_val)
                                            app_name_from_api = item.get("cli", "") or service_info.get('service_name', '')
                                            break
                                first_poll = False
                            elif resp.get("status") == "success":
                                first_poll = False
                    except:
                        pass
                elif fmt_name == "ins_agent" and sms_endpoint:
                    # ins_agent: poll OTP endpoint filtered by phone number
                    try:
                        res = req_session.get(sms_endpoint, headers=headers, timeout=15)
                        if res.status_code == 200:
                            resp = res.json()
                            if resp.get("ok") and isinstance(resp.get("data"), list):
                                for item in resp["data"]:
                                    item_id = item.get("id", "")
                                    if first_poll:
                                        seen_otp_ids.add(item_id)
                                        continue
                                    if item_id and item_id not in seen_otp_ids:
                                        seen_otp_ids.add(item_id)
                                        otp_val = item.get("otp_code") or ""
                                        sms_val = item.get("message_text") or item.get("sms") or ""
                                        if not otp_val and sms_val:
                                            m = re.search(r'(\d{4,8})', sms_val)
                                            if m: otp_val = m.group(1)
                                        if otp_val:
                                            has_otp = True
                                            otp_code = str(otp_val)
                                            full_sms = str(sms_val)
                                            app_name_from_api = item.get("platform") or item.get("service") or service_info.get('service_name', '')
                                            break
                                first_poll = False
                            elif resp.get("ok"):
                                first_poll = False
                    except:
                        pass
                elif p_type == "login":
                    # Login-based panels: try multiple endpoints
                    result = _poll_manual_login_panel(panel, panel_id, phone_number, sess, headers, fmt_name)
                    if result and result.get("otp"):
                        has_otp = True
                        otp_code = result["otp"]
                        full_sms = result.get("sms", "")
                        app_name_from_api = result.get("service", "") or service_info.get('service_name', '')
                else:
                    # Other API panels with manual numbers: try common OTP endpoints
                    base = _get_api_base(api_url, fmt_name)
                    manual_endpoints = [
                        f"{base}/api/functions/agent-api/otp?number={clean_phone}&limit=5",
                        f"{base}/api/getSms?number={clean_phone}",
                        f"{base}/api/getStatus?number={clean_phone}",
                        f"{base}/sms/latest",
                    ]
                    for ep in manual_endpoints:
                        try:
                            res = req_session.get(ep, headers=headers, timeout=10)
                            if res.status_code != 200:
                                continue
                            resp = res.json()
                            # ins_agent style response
                            if resp.get("ok") and isinstance(resp.get("data"), list):
                                for item in resp["data"]:
                                    item_num = str(item.get("number", "")).replace("+", "")
                                    if item_num == clean_phone or clean_phone.endswith(item_num) or item_num.endswith(clean_phone):
                                        item_id = item.get("id", "")
                                        if first_poll:
                                            seen_otp_ids.add(item_id)
                                            continue
                                        if item_id and item_id not in seen_otp_ids:
                                            seen_otp_ids.add(item_id)
                                            otp_val = item.get("otp_code") or item.get("code") or item.get("otp") or ""
                                            sms_val = item.get("message_text") or item.get("sms") or ""
                                            if not otp_val and sms_val:
                                                m2 = re.search(r'(\d{4,8})', sms_val)
                                                if m2: otp_val = m2.group(1)
                                            if otp_val:
                                                has_otp = True
                                                otp_code = str(otp_val)
                                                full_sms = str(sms_val)
                                                app_name_from_api = item.get("platform") or item.get("service") or service_info.get('service_name', '')
                                                break
                                first_poll = False
                            elif resp.get("ok"):
                                first_poll = False
                            # Standard response with status
                            elif resp.get("status") in ("OK", "SUCCESS", "1", "ok") and (resp.get("code") or resp.get("otp") or resp.get("sms")):
                                otp_val = resp.get("code") or resp.get("otp") or ""
                                sms_val = resp.get("sms") or resp.get("message") or ""
                                if otp_val:
                                    has_otp = True
                                    otp_code = str(otp_val)
                                    full_sms = str(sms_val)
                            if has_otp:
                                break
                        except:
                            continue
            # === STANDARD (AUTO) NUMBER POLLING ===
            else:
                if not sms_endpoint:
                    time.sleep(3)
                    continue
                if p_type == "login" and panel_id:
                    sess = get_login_session(panel_id)
                    if sess and sess.get("session"):
                        res = sess["session"].get(sms_endpoint, headers=headers, timeout=15)
                    else:
                        res = req_session.get(sms_endpoint, headers=headers, timeout=15)
                else:
                    res = req_session.get(sms_endpoint, headers=headers, timeout=15)
                s_data = res.json()
                
                if fmt_name == "ins_agent" and s_data.get("ok") and s_data.get("data"):
                    sms_list = s_data["data"]
                    if isinstance(sms_list, list) and len(sms_list) > 0:
                        latest = sms_list[0]
                        s_data = latest
                elif fmt.get("data_wrapper") and fmt["data_wrapper"] in s_data:
                    wrapped = s_data[fmt["data_wrapper"]]
                    if isinstance(wrapped, list) and len(wrapped) > 0:
                        s_data = wrapped[0]
                    elif isinstance(wrapped, dict):
                        s_data = wrapped
                
                parsed_sms = parse_sms_response(panel, s_data) if panel else None
                if parsed_sms and parsed_sms["success"] and parsed_sms["otp"]:
                    has_otp = True
                    otp_code = parsed_sms["otp"]
                    full_sms = parsed_sms["sms"] or ""
                    app_name_from_api = parsed_sms.get("service", "") or s_data.get("service", "") or s_data.get("platform", "") or s_data.get("app_name", service_info.get('service_name', ''))
                elif s_data.get("otp_code") or s_data.get("message_text"):
                    has_otp = True
                    otp_code = s_data.get("otp_code") or ""
                    full_sms = s_data.get("message_text", "") or s_data.get("sms", "")
                    if not otp_code and full_sms:
                        m = re.search(r'(\d{4,8})', full_sms)
                        if m: otp_code = m.group(1)
                    if otp_code:
                        app_name_from_api = s_data.get("platform", "") or s_data.get("service", "") or s_data.get("app_name", service_info.get('service_name', ''))
                    else:
                        has_otp = False
                elif s_data.get("success") and s_data.get("otp"):
                    has_otp = True
                    otp_code = s_data.get("otp")
                    full_sms = s_data.get("message", "") or s_data.get("sms", "")
                    app_name_from_api = s_data.get("service", "") or s_data.get("app_name", service_info.get('service_name', ''))
            
            if has_otp:
                full_otp = str(otp_code)
                match1 = re.search(r'(?:code\D+)?(\d{3,6}[- ]\d{3,6})', full_sms, re.IGNORECASE)
                if match1:
                    full_otp = match1.group(1).strip()
                else:
                    match2 = re.search(r'(?:code|otp|kod)\D+(\d{4,8})', full_sms, re.IGNORECASE)
                    if match2:
                        full_otp = match2.group(1)
                    else:
                        match3 = re.search(r'(\d{4,8})', full_sms)
                        if match3:
                            full_otp = match3.group(1)
                
                if len(full_otp) > len(str(otp_code)):
                    otp_code = full_otp
                
                detected_service = detect_service_from_sms(full_sms, app_name_from_api)
                
                if detected_service == "Unknown" and app_name_from_api and app_name_from_api != service_info.get('service_name', ''):
                    detected_service = app_name_from_api.title()
                
                lang_code = detect_language(full_sms)
                update_number_status(chat_id, phone_number, "OTP RECEIVED", "✅")
                increment_sms_count()
                log_traffic(detected_service, service_info.get("country_name", "Unknown"))
                
                data = load_data()
                watermark = data.get("watermark", "DXA UNIVERSE")
                
                try:
                    chat = bot.get_chat(chat_id)
                    update_leaderboard(chat_id, chat.first_name)
                except: pass
                
                clean_num = str(phone_number).replace('+', '')
                masked_num = mask_number(phone_number)
                srv_short = get_short_service(detected_service)
                flag = get_country_flag(service_info.get('country_name', ''))
                cc = get_iso_code(service_info.get('country_name', ''))
                srv_emoji = emo(detected_service)
                panel_name = num_data.get("panel_name", "")
                panel_label = f" 📋{html.escape(panel_name)}" if panel_name else ""
                
                # INBOX MSG - sent to user in bot
                inbox_msg = (
                    f"{flag} #{cc} {srv_emoji} +{clean_num}{panel_label}\n"
                    f"\n"
                    f"永 <b>POWERED BY {html.escape(watermark)}</b> 🔴"
                )
                
                inbox_markup = InlineKeyboardMarkup(row_width=1)
                inbox_markup.add(ibtn(f"🔑 📋 OTP: {otp_code}", copy_text_str=otp_code, style="success"))
                
                safe_send(chat_id, inbox_msg, inbox_markup)
                
                main_link_grp = format_url(data.get("main_otp_link", "https://t.me/"))
                
                # GROUP MSG - sent to all forward groups
                group_msg = (
                    f"{flag} #{cc} {srv_emoji} +{masked_num}{panel_label}\n"
                    f"\n"
                    f"永 <b>POWERED BY {html.escape(watermark)}</b> 🔴"
                )
                
                for grp in data.get("forward_groups", []):
                    try:
                        grp_markup = InlineKeyboardMarkup(row_width=1)
                        grp_markup.add(ibtn(f"🔑 📋 OTP: {otp_code}", copy_text_str=otp_code, style="success"))
                        color_cycle_grp = ["danger", "primary", "success"]
                        for b_idx, btn in enumerate(grp.get("buttons", [])):
                            grp_markup.add(ibtn(btn['name'], url=btn['url'], style=color_cycle_grp[b_idx % len(color_cycle_grp)]))
                        safe_send(grp['chat_id'], group_msg, grp_markup)
                    except: pass
                
                # Admin notification
                try:
                    if chat_id != ADMIN_ID:
                        admin_msg = (
                            f"🔔 <b>OTP RECEIVED</b>\n"
                            f"━━━━━━━━━━━━━━━\n"
                            f"👤 User: <code>{chat_id}</code>\n"
                            f"{flag} #{cc} {srv_emoji} +{clean_num}\n"
                            f"🔑 OTP: <code>{otp_code}</code>\n"
                            f"📋 Panel: {panel_label}\n"
                            f"━━━━━━━━━━━━━━━"
                        )
                        safe_send(ADMIN_ID, admin_msg)
                except: pass
                return
        except: pass
        time.sleep(3)
    
    update_number_status(chat_id, phone_number, "TIMEOUT", "⏰")

# ==================== GLOBAL SMS LISTENER ====================
forwarded_sms_ids = set()

def global_sms_listener():
    while True:
        try:
            data = load_data()
            panels = data.get("panels", {})
            active_panels = [(pid, p) for pid, p in panels.items() if p.get("status") == "active" and p.get("api_url") and (p.get("api_key") or (p.get("type") == "login" and p.get("login_user")))]
            
            for panel_id, panel in active_panels:
                p_type = panel.get("type", "api")
                sess = None
                if p_type == "login":
                    sess = get_login_session(panel_id)
                    if sess and sess.get("token"):
                        headers = {'Authorization': f'Bearer {sess["token"]}'}
                    else:
                        headers = {}
                else:
                    headers = get_api_headers(panel)
                api_url = panel['api_url'].rstrip('/')
                p_name = panel.get("name", "")
                p_label = f" \ud83d\udccb{html.escape(p_name)}" if p_name else ""
                
                fmt_name = panel.get("api_format", detect_panel_format(api_url, panel.get("api_key", "")))
                
                if fmt_name == "ins_agent":
                    latest_endpoint = build_api_url(panel, "get_sms", number_id="")
                    if not latest_endpoint:
                        latest_endpoint = f"{api_url}/api/functions/agent-api/otp?limit=10"
                elif fmt_name == "nexaotp":
                    continue
                else:
                    latest_endpoint = build_api_url(panel, "get_latest_sms")
                    if not latest_endpoint:
                        base = api_url.rsplit('/', 1)[0] if '/' in api_url else api_url
                        latest_endpoint = f"{base}/sms/latest"
                
                try:
                    if p_type == "login" and sess and sess.get("session"):
                        res = sess["session"].get(latest_endpoint, headers=headers, timeout=10)
                    else:
                        res = req_session.get(latest_endpoint, headers=headers, timeout=10)
                    s_data = res.json()
                    
                    messages_list = []
                    if fmt_name == "ins_agent" and s_data.get("ok"):
                        messages_list = s_data.get("data", [])
                    elif s_data.get("success"):
                        messages_list = s_data.get("messages") or s_data.get("data", [])
                    
                    for msg in messages_list:
                        msg_id = msg.get("id") or msg.get("sms_id")
                        
                        if msg_id and msg_id not in forwarded_sms_ids:
                            forwarded_sms_ids.add(msg_id)
                            
                            number = msg.get("number", "Unknown")
                            sms_text = msg.get("sms", "") or msg.get("message", "") or msg.get("message_text", "")
                            otp_code = msg.get("otp", "") or msg.get("otp_code", "")
                            app_name = msg.get("service", "") or msg.get("app_name", "") or msg.get("platform", "")
                            
                            detected_service = detect_service_from_sms(sms_text, app_name)
                            lang_code = detect_language(sms_text)
                            masked_num = mask_number(number)
                            srv_short = get_short_service(detected_service)
                            
                            raw_num = str(number).replace('+', '')
                            detected_country = get_country_from_number(raw_num)
                            flag = get_country_flag(detected_country)
                            cc = get_iso_code(detected_country)
                            srv_emoji = emo(detected_service)
                            
                            gl_watermark = data.get("watermark", "DXA UNIVERSE")
                            
                            group_msg = (
                                f"{flag} #{cc} {srv_emoji} +{masked_num}{p_label}\n"
                                f"\n"
                                f"永 <b>POWERED BY {html.escape(gl_watermark)}</b> 🔴"
                            )
                            
                            for grp in data.get("forward_groups", []):
                                try:
                                    grp_markup = InlineKeyboardMarkup(row_width=1)
                                    if otp_code:
                                        grp_markup.add(ibtn(f"🔑 📋 OTP: {otp_code}", copy_text_str=otp_code, style="success"))
                                    color_cycle_gl = ["danger", "primary", "success"]
                                    for b_idx, btn in enumerate(grp.get("buttons", [])):
                                        grp_markup.add(ibtn(btn['name'], url=btn['url'], style=color_cycle_gl[b_idx % len(color_cycle_gl)]))
                                    safe_send(grp['chat_id'], group_msg, grp_markup)
                                except: pass
                except: pass
        except Exception as e:
            pass
        
        time.sleep(5)

if __name__ == "__main__":
    try:
        bot.set_my_commands([telebot.types.BotCommand("/start", "🚀 Start Number Bot")])
    except: pass
    
    print("🔄 Starting Global SMS Listener...")
    threading.Thread(target=global_sms_listener, daemon=True).start()
    
    print("👑 SpyX Premium - Bot Running with Custom Colorful Buttons! 👑")
    bot.infinity_polling(timeout=30, long_polling_timeout=25, allowed_updates=["message", "callback_query"])
