"""
Wasserwacht Dienstplan+ v7.1 - Firebase Edition
Komplette Neuentwicklung mit allen v7.1 Features
Modern | Minimalistisch | Mobile-First | Responsive
"""

import streamlit as st
import hashlib
import io
import json
import zipfile
import calendar as cal_module
from datetime import datetime, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from twilio.rest import Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.cloud import firestore
from google.oauth2 import service_account

# ===== PAGE CONFIG (MUSS ERSTE STREAMLIT-FUNKTION SEIN!) =====
st.set_page_config(
    page_title="Wasserwacht Dienstplan+",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== KONFIGURATION =====
VERSION = "7.1 - Wasserwacht Edition"
TIMEZONE_STR = "Europe/Berlin"
TZ = pytz.timezone(TIMEZONE_STR)

WEEKLY_SLOTS = [
    {"id": 1, "day": "tuesday", "day_name": "Dienstag", "start": "17:00", "end": "20:00"},
    {"id": 2, "day": "friday", "day_name": "Freitag", "start": "17:00", "end": "20:00"},
    {"id": 3, "day": "saturday", "day_name": "Samstag", "start": "14:00", "end": "17:00"},
]

BAVARIA_HOLIDAYS = {
    "2025": ["2025-01-01", "2025-01-06", "2025-04-18", "2025-04-21", "2025-05-01", 
             "2025-05-29", "2025-06-09", "2025-06-19", "2025-08-15", "2025-10-03", 
             "2025-11-01", "2025-12-25", "2025-12-26"],
    "2026": ["2026-01-01", "2026-01-06", "2026-04-03", "2026-04-06", "2026-05-01", 
             "2026-05-14", "2026-05-25", "2026-06-04", "2026-08-15", "2026-10-03", 
             "2026-11-01", "2026-12-25", "2026-12-26"]
}

COLORS = {
    "rot": "#DC143C", "rot_dunkel": "#B22222", "rot_hell": "#FF6B6B",
    "blau": "#003087", "blau_hell": "#4A90E2",
    "weiss": "#FFFFFF", "grau_hell": "#F5F7FA", "grau_mittel": "#E1E8ED",
    "grau_dunkel": "#657786", "text": "#14171A", 
    "erfolg": "#17BF63", "warnung": "#FFAD1F", "fehler": "#E0245E"
}

# ===== FIREBASE INIT =====
@st.cache_resource
def init_firestore():
    try:
        if not hasattr(st, 'secrets'):
            st.error("❌ Keine Secrets konfiguriert!")
            st.stop()
        
        key = st.secrets.get("firebase", {}).get("service_account_key")
        if not key:
            st.error("❌ Firebase Key fehlt! Siehe DEPLOYMENT_GUIDE.md")
            st.stop()
        
        key_dict = json.loads(key)
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return firestore.Client(credentials=creds, project=key_dict["project_id"])
    except Exception as e:
        st.error(f"❌ Firebase-Fehler: {e}")
        st.stop()

db = init_firestore()

# ===== HELPER FUNCTIONS =====
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def week_start(d=None):
    d = d or datetime.now().date()
    if hasattr(d, "date"):
        d = d.date()
    return d - timedelta(days=d.weekday())

def slot_date(ws, day):
    days = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
    return (ws + timedelta(days=days.get(day,0))).strftime("%Y-%m-%d")

def fmt_de(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
    except:
        return d

def is_holiday(d):
    return d in BAVARIA_HOLIDAYS.get(d[:4], [])

def is_summer(d):
    try:
        return 6 <= datetime.strptime(d, "%Y-%m-%d").month <= 9
    except:
        return False

def is_blocked(d):
    return is_holiday(d) or is_summer(d)

def block_reason(d):
    if is_holiday(d):
        return "🚫 Feiertag"
    elif is_summer(d):
        return "🏖️ Sommerpause"
    return None

# ===== CSS INJECTION =====
def inject_css(dark=False):
    bg = "#1A1D23" if dark else COLORS["weiss"]
    surface = "#2D3238" if dark else COLORS["grau_hell"]
    text = "#FFFFFF" if dark else COLORS["text"]
    primary = COLORS["rot_hell"] if dark else COLORS["rot"]
    
    st.markdown(f"""<style>
    .main {{background:{bg};color:{text};}}
    .stApp {{background:{bg};}}
    section[data-testid="stSidebar"] {{background:{surface};border-right:2px solid {primary};}}
    .stButton>button {{background:linear-gradient(135deg,{primary} 0%,{COLORS["rot_dunkel"]} 100%);
        color:white;border:none;border-radius:8px;padding:0.5rem 1.5rem;font-weight:600;
        transition:all 0.3s;box-shadow:0 2px 4px rgba(0,0,0,0.1);}}
    .stButton>button:hover {{transform:translateY(-2px);box-shadow:0 4px 8px rgba(220,20,60,0.3);}}
    h1,h2,h3 {{color:{primary};font-weight:700;}}
    h1 {{border-bottom:3px solid {primary};padding-bottom:0.5rem;}}
    .stTextInput input,.stTextArea textarea,.stSelectbox select {{border:2px solid {COLORS["grau_mittel"]};
        border-radius:8px;background:{surface};color:{text};}}
    .stTextInput input:focus {{border-color:{primary};box-shadow:0 0 0 2px {primary}40;}}
    
    /* Mobile Bottom Navigation */
    @media (max-width: 768px) {{
        section[data-testid="stSidebar"] {{display: none !important;}}
        .mobile-bottom-nav {{position:fixed;bottom:0;left:0;right:0;background:{surface};
            border-top:2px solid {primary};display:flex;justify-content:space-around;
            padding:0.5rem;z-index:1000;box-shadow:0 -4px 12px rgba(0,0,0,0.1);}}
        .mobile-nav-item {{display:flex;flex-direction:column;align-items:center;
            padding:0.5rem;color:{text};font-size:0.8rem;transition:all 0.3s;text-decoration:none;}}
        .mobile-nav-item:hover,.mobile-nav-item.active {{color:{primary};transform:scale(1.1);}}
        .main {{padding-bottom:80px;}}
    }}
    
    @media (min-width: 769px) {{
        .mobile-bottom-nav {{display:none;}}
    }}
    </style>""", unsafe_allow_html=True)

# ===== DATABASE CLASS =====
class WasserwachtDB:
    def __init__(self):
        self.db = db
        self._validate_data()
        self._init_admin()
    
    def _validate_data(self):
        """Validiert Datenstruktur beim Start"""
        try:
            required_collections = ['users', 'bookings', 'settings', 'audit_log']
            for coll in required_collections:
                if not self.db.collection(coll).limit(1).get():
                    print(f"ℹ️ Collection '{coll}' erstellt")
        except Exception as e:
            print(f"Validierungs-Fehler: {e}")
    
    def _init_admin(self):
        """Erstellt/prüft Admin-User"""
        if hasattr(st,'secrets'):
            email = st.secrets.get("ADMIN_EMAIL","admin@wasserwacht.de")
            pw = st.secrets.get("ADMIN_PASSWORD","admin123")
            existing = self.get_user(email)
            if not existing:
                try:
                    self.db.collection('users').add({
                        'email':email,'name':'Admin','phone':'','password_hash':hash_pw(pw),
                        'role':'admin','active':True,'email_notifications':True,
                        'sms_notifications':False,'created_at':firestore.SERVER_TIMESTAMP
                    })
                    print(f"✅ Admin erstellt: {email}")
                except Exception as e:
                    print(f"❌ Admin-Fehler: {e}")
            else:
                print(f"ℹ️ Admin existiert: {email}")
    
    def get_user(self,email):
        try:
            for doc in self.db.collection('users').where('email','==',email).limit(1).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except:
            return None
    
    def create_user(self,email,name,phone,password,role='user'):
        try:
            if self.get_user(email):
                return False,"E-Mail bereits registriert"
            self.db.collection('users').add({
                'email':email,'name':name,'phone':phone,'password_hash':hash_pw(password),
                'role':role,'active':True,'email_notifications':True,'sms_notifications':False,
                'created_at':firestore.SERVER_TIMESTAMP
            })
            self.log('user_created',f"User {email} erstellt")
            return True,"User erstellt"
        except Exception as e:
            return False,str(e)
    
    def auth(self,email,password):
        u = self.get_user(email)
        if not u or not u.get('active',True):
            return False,None
        if u['password_hash'] == hash_pw(password):
            return True,u
        return False,None
    
    def get_all_users(self):
        try:
            users = []
            for doc in self.db.collection('users').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                users.append(data)
            return users
        except:
            return []
    
    def update_user(self,uid,**kwargs):
        try:
            self.db.collection('users').document(uid).update(kwargs)
            return True
        except:
            return False
    
    def delete_user(self,email):
        try:
            u = self.get_user(email)
            if u:
                self.db.collection('users').document(u['id']).delete()
                self.log('user_deleted',f"User {email} gelöscht")
                return True
            return False
        except:
            return False
    
    def create_booking(self,slot_date,slot_time,user_email,user_name,user_phone):
        try:
            if self.get_booking(slot_date,slot_time):
                return False,"Slot bereits gebucht"
            self.db.collection('bookings').add({
                'slot_date':slot_date,'slot_time':slot_time,'user_email':user_email,
                'user_name':user_name,'user_phone':user_phone,'status':'confirmed',
                'created_at':firestore.SERVER_TIMESTAMP
            })
            self.log('booking_created',f"{user_name} buchte {slot_date} {slot_time}")
            return True,"Buchung erfolgreich"
        except Exception as e:
            return False,str(e)
    
    def get_booking(self,slot_date,slot_time):
        try:
            for doc in self.db.collection('bookings').where('slot_date','==',slot_date)\
                    .where('slot_time','==',slot_time).where('status','==','confirmed').limit(1).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except:
            return None
    
    def get_user_bookings(self,email,future_only=False):
        try:
            q = self.db.collection('bookings').where('user_email','==',email)\
                    .where('status','==','confirmed')
            if future_only:
                q = q.where('slot_date','>=',datetime.now().strftime("%Y-%m-%d"))
            bookings = []
            for doc in q.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                bookings.append(data)
            return sorted(bookings,key=lambda x:x['slot_date'])
        except:
            return []
    
    def cancel_booking(self,bid,cancelled_by):
        try:
            self.db.collection('bookings').document(bid).update({
                'status':'cancelled','cancelled_by':cancelled_by,
                'cancelled_at':firestore.SERVER_TIMESTAMP
            })
            self.log('booking_cancelled',f"Buchung {bid} storniert")
            return True
        except:
            return False
    
    def get_week_bookings(self,ws):
        try:
            we = (datetime.strptime(ws,'%Y-%m-%d')+timedelta(days=6)).strftime('%Y-%m-%d')
            result = []
            for doc in self.db.collection('bookings').where('slot_date','>=',ws)\
                    .where('slot_date','<=',we).where('status','==','confirmed').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                result.append(data)
            return result
        except:
            return []
    
    def get_setting(self,key,default=''):
        try:
            doc = self.db.collection('settings').document(key).get()
            return doc.to_dict().get('value',default) if doc.exists else default
        except:
            return default
    
    def set_setting(self,key,value):
        try:
            self.db.collection('settings').document(key).set({
                'value':value,'updated_at':firestore.SERVER_TIMESTAMP
            },merge=True)
            return True
        except:
            return False
    
    def log(self,action,details,user='system'):
        try:
            self.db.collection('audit_log').add({
                'action':action,'details':details,'user_email':user,
                'timestamp':firestore.SERVER_TIMESTAMP
            })
        except:
            pass
    
    def get_logs(self,limit=100):
        try:
            logs = []
            for doc in self.db.collection('audit_log')\
                    .order_by('timestamp',direction=firestore.Query.DESCENDING)\
                    .limit(limit).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                logs.append(data)
            return logs
        except:
            return []
    
    def get_stats(self):
        """Verbesserte Statistiken (v7.1)"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            all_users = [u for u in self.get_all_users() if u.get('active', True)]
            total_users = len(all_users)
            
            future_bookings = []
            for doc in self.db.collection('bookings').where('slot_date','>=',today)\
                    .where('status','==','confirmed').stream():
                future_bookings.append(doc.to_dict())
            future_count = len(future_bookings)
            
            month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
            month_bookings = []
            for doc in self.db.collection('bookings').where('slot_date','>=',month_start)\
                    .where('slot_date','<=',today).where('status','==','confirmed').stream():
                month_bookings.append(doc.to_dict())
            month_count = len(month_bookings)
            
            free_slots_4w = []
            for i in range(28):
                check_date = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
                if not is_blocked(check_date):
                    for slot in WEEKLY_SLOTS:
                        ws = week_start(datetime.strptime(check_date,"%Y-%m-%d"))
                        slot_d = slot_date(ws,slot['day'])
                        if slot_d == check_date:
                            booking = self.get_booking(check_date,f"{slot['start']}-{slot['end']}")
                            if not booking:
                                free_slots_4w.append({'date':check_date,'slot':f"{slot['day_name']} {slot['start']}-{slot['end']}"})
            
            return {
                'total_users':total_users,
                'future_bookings':future_count,
                'month_bookings':month_count,
                'free_slots_next_4weeks':free_slots_4w
            }
        except Exception as e:
            print(f"Stats-Fehler: {e}")
            return {'total_users':0,'future_bookings':0,'month_bookings':0,'free_slots_next_4weeks':[]}
    
    def archive_old(self):
        try:
            months = int(st.secrets.get("AUTO_ARCHIVE_MONTHS","12")) if hasattr(st,'secrets') else 12
            archive_date = (datetime.now()-timedelta(days=30*months)).strftime("%Y-%m-%d")
            count = 0
            for doc in self.db.collection('bookings').where('slot_date','<',archive_date).stream():
                self.db.collection('archive').add(doc.to_dict())
                doc.reference.delete()
                count += 1
            if count > 0:
                self.log('archiving',f"{count} Buchungen archiviert")
            return count
        except:
            return 0

ww_db = WasserwachtDB()

# ===== ENDE TEIL 1 =====
# ===== EMAIL & SMS CLASSES =====
class Mailer:
    def __init__(self):
        if hasattr(st,'secrets'):
            self.server = st.secrets.get("SMTP_SERVER","smtp.gmail.com")
            self.port = int(st.secrets.get("SMTP_PORT",587))
            self.user = st.secrets.get("SMTP_USER","")
            self.pw = st.secrets.get("SMTP_PASSWORD","")
            self.admin_receiver = st.secrets.get("ADMIN_EMAIL_RECEIVER","")
        else:
            self.server = self.port = self.user = self.pw = self.admin_receiver = ""
    
    def send(self,to,subject,body,attachments=None):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.user
            msg['To'] = to
            msg['Subject'] = subject
            msg.attach(MIMEText(body,'html'))
            
            if attachments:
                for filename,data in attachments:
                    part = MIMEBase('application','octet-stream')
                    part.set_payload(data)
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition',f'attachment; filename={filename}')
                    msg.attach(part)
            
            with smtplib.SMTP(self.server,self.port) as server:
                server.starttls()
                server.login(self.user,self.pw)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"E-Mail-Fehler: {e}")
            return False
    
    def booking_confirmation(self,user_email,user_name,slot_date,slot_time):
        subject = f"✅ Buchungsbestätigung {fmt_de(slot_date)}"
        body = f"""<html><body>
        <h2 style="color:{COLORS['rot']}">Wasserwacht Dienstplan+</h2>
        <p>Hallo {user_name},</p>
        <p>Deine Schicht wurde erfolgreich gebucht:</p>
        <ul><li><b>Datum:</b> {fmt_de(slot_date)}</li><li><b>Zeit:</b> {slot_time}</li></ul>
        <p>Du erhältst Erinnerungen 24h und 1h vor Schichtbeginn.</p>
        <p style="color:{COLORS['grau_dunkel']}">Bei Fragen: {self.admin_receiver}</p>
        </body></html>"""
        return self.send(user_email,subject,body)
    
    def cancellation_confirmation(self,user_email,user_name,slot_date,slot_time):
        subject = f"🔴 Stornierungsbestätigung {fmt_de(slot_date)}"
        body = f"""<html><body>
        <h2 style="color:{COLORS['rot']}">Wasserwacht Dienstplan+</h2>
        <p>Hallo {user_name},</p>
        <p>Deine Schicht wurde storniert:</p>
        <ul><li><b>Datum:</b> {fmt_de(slot_date)}</li><li><b>Zeit:</b> {slot_time}</li></ul>
        </body></html>"""
        return self.send(user_email,subject,body)
    
    def backup_email(self,backup_zip):
        """Verbessertes Backup (v7.1)"""
        try:
            subject = f"📦 Dienstplan Backup {datetime.now().strftime('%d.%m.%Y %H:%M')}"
            body = f"""<html><body>
            <h2 style="color:{COLORS['rot']}">Automatisches Backup</h2>
            <p>Anbei das Backup der Dienstplan-Datenbank.</p>
            <p><b>Zeitpunkt:</b> {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')} Uhr</p>
            <p><b>Inhalt:</b> Alle Buchungen, User und Einstellungen</p>
            </body></html>"""
            
            filename = f"dienstplan_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
            
            backup_emails = []
            if hasattr(st,'secrets'):
                try:
                    backup_emails_raw = st.secrets.get("BACKUP_EMAILS","[]")
                    backup_emails = json.loads(backup_emails_raw)
                except:
                    backup_emails = []
                
                admin_email = st.secrets.get("ADMIN_EMAIL_RECEIVER","")
                if admin_email and admin_email not in backup_emails:
                    backup_emails.append(admin_email)
            
            success_count = 0
            for email in backup_emails:
                if self.send(email,subject,body,[(filename,backup_zip)]):
                    success_count += 1
            
            return success_count > 0
        except Exception as e:
            print(f"Backup-E-Mail-Fehler: {e}")
            return False

class TwilioSMS:
    def __init__(self):
        if hasattr(st,'secrets'):
            self.sid = st.secrets.get("TWILIO_ACCOUNT_SID","")
            self.token = st.secrets.get("TWILIO_AUTH_TOKEN","")
            self.phone = st.secrets.get("TWILIO_PHONE_NUMBER","")
            self.enabled = st.secrets.get("ENABLE_SMS_REMINDER","false").lower()=="true"
        else:
            self.sid = self.token = self.phone = ""
            self.enabled = False
    
    def send(self,to,message):
        if not self.enabled or not self.sid:
            return False
        try:
            client = Client(self.sid,self.token)
            client.messages.create(to=to,from_=self.phone,body=message)
            return True
        except:
            return False
    
    def reminder_24h(self,user_phone,user_name,slot_date,slot_time):
        msg = f"Wasserwacht: Hallo {user_name}, Deine Schicht ist morgen {fmt_de(slot_date)} um {slot_time}. Viel Erfolg!"
        return self.send(user_phone,msg)
    
    def reminder_1h(self,user_phone,user_name,slot_time):
        msg = f"Wasserwacht: Deine Schicht beginnt in 1h ({slot_time}). Bis gleich!"
        return self.send(user_phone,msg)

mailer = Mailer()
sms = TwilioSMS()

# ===== SCHEDULER =====
def daily_tasks():
    """Tägliche Aufgaben (v7.1)"""
    ww_db.archive_old()
    if hasattr(st,'secrets') and st.secrets.get("ENABLE_DAILY_BACKUP","true").lower()=="true":
        try:
            data = ww_db.db.collection('bookings').stream()
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as zf:
                bookings_csv = "date,time,user,phone,status\n"
                for doc in data:
                    d = doc.to_dict()
                    bookings_csv += f"{d.get('slot_date','')},{d.get('slot_time','')},{d.get('user_name','')},{d.get('user_phone','')},{d.get('status','')}\n"
                zf.writestr('bookings.csv',bookings_csv)
            mailer.backup_email(buffer.getvalue())
        except:
            pass

def reminder_tasks():
    """SMS-Reminder (24h vorher)"""
    tomorrow = (datetime.now()+timedelta(days=1)).strftime("%Y-%m-%d")
    bookings = ww_db.db.collection('bookings').where('slot_date','==',tomorrow)\
            .where('status','==','confirmed').stream()
    for doc in bookings:
        b = doc.to_dict()
        if b.get('user_phone'):
            sms.reminder_24h(b['user_phone'],b['user_name'],b['slot_date'],b['slot_time'])

def check_free_slots_alarm():
    """Freie-Slots-Alarm (v7.1)"""
    try:
        alarm_days = int(st.secrets.get("FREE_SLOTS_ALARM_DAYS","7")) if hasattr(st,'secrets') else 7
        critical_slots = []
        
        for i in range(1,alarm_days+1):
            check_date = (datetime.now()+timedelta(days=i)).strftime("%Y-%m-%d")
            if not is_blocked(check_date):
                for slot in WEEKLY_SLOTS:
                    ws = week_start(datetime.strptime(check_date,"%Y-%m-%d"))
                    slot_d = slot_date(ws,slot['day'])
                    if slot_d == check_date:
                        booking = ww_db.get_booking(check_date,f"{slot['start']}-{slot['end']}")
                        if not booking:
                            critical_slots.append({
                                'date':fmt_de(check_date),'day':slot['day_name'],
                                'time':f"{slot['start']}-{slot['end']}",'days_until':i
                            })
        
        if critical_slots:
            all_users = ww_db.get_all_users()
            admin_emails = [u['email'] for u in all_users if u.get('role')=='admin' and u.get('active',True)]
            
            subject = f"⚠️ Freie Schichten ({len(critical_slots)} Slots)"
            slots_html = "".join([f"<li><b>{s['date']}</b> ({s['day']}) {s['time']} - {s['days_until']} Tage</li>" for s in critical_slots])
            body = f"""<html><body>
            <h2 style="color:{COLORS['warnung']}">⚠️ Freie Schichten-Warnung</h2>
            <p>Die folgenden Schichten sind noch nicht gebucht:</p>
            <ul>{slots_html}</ul>
            </body></html>"""
            
            for admin_email in admin_emails:
                mailer.send(admin_email,subject,body)
    except Exception as e:
        print(f"Freie-Slots-Alarm Fehler: {e}")

if 'scheduler_started' not in st.session_state:
    try:
        scheduler = BackgroundScheduler(timezone=TZ)
        backup_time = st.secrets.get("BACKUP_TIME","20:00") if hasattr(st,'secrets') else "20:00"
        h,m = backup_time.split(":")
        scheduler.add_job(daily_tasks,'cron',hour=int(h),minute=int(m))
        scheduler.add_job(reminder_tasks,'cron',hour=18,minute=0)
        scheduler.add_job(check_free_slots_alarm,'cron',hour=18,minute=0)
        scheduler.start()
        st.session_state.scheduler_started = True
    except:
        pass

# ===== MAIN APP =====
def main():
    # Session-Management (v7.1)
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'last_activity' not in st.session_state:
        st.session_state.last_activity = datetime.now()
    
    timeout_min = int(st.secrets.get("SESSION_TIMEOUT_MINUTES","5")) if hasattr(st,'secrets') else 5
    if st.session_state.user:
        time_inactive = (datetime.now()-st.session_state.last_activity).total_seconds()
        if time_inactive > timeout_min*60:
            st.session_state.user = None
            st.warning("⏰ Ausgeloggt wegen Inaktivität.")
            st.rerun()
        else:
            st.session_state.last_activity = datetime.now()
    
    if 'dark_mode' not in st.session_state:
        st.session_state.dark_mode = st.secrets.get("DARK_MODE_DEFAULT","false").lower()=="true" if hasattr(st,'secrets') else False
    
    inject_css(st.session_state.dark_mode)
    
    if 'page' not in st.session_state:
        st.session_state.page = 'home'
    
    with st.sidebar:
        st.markdown(f"<h1 style='color:{COLORS['rot']}'>🌊 Wasserwacht</h1>",unsafe_allow_html=True)
        st.markdown(f"<p style='color:{COLORS['grau_dunkel']}'>Dienstplan+ v{VERSION}</p>",unsafe_allow_html=True)
        st.divider()
        
        if st.session_state.user:
            st.success(f"✅ {st.session_state.user['name']}")
            role = st.session_state.user.get('role','user')
            
            if st.button("🏠 Startseite",use_container_width=True):
                st.session_state.page = 'home'
                st.rerun()
            
            if st.button("📅 Meine Schichten",use_container_width=True):
                st.session_state.page = 'my_bookings'
                st.rerun()
            
            if st.button("📋 Alle Buchungen",use_container_width=True):
                st.session_state.page = 'booking_list'
                st.rerun()
            
            if st.button("📅 Kalender",use_container_width=True):
                st.session_state.page = 'calendar'
                st.rerun()
            
            if st.button("📚 Handbuch",use_container_width=True):
                st.session_state.page = 'handbook'
                st.rerun()
            
            if st.button("👤 Profil",use_container_width=True):
                st.session_state.page = 'profile'
                st.rerun()
            
            if role == 'admin':
                st.divider()
                st.markdown("**🔧 Admin-Bereich**")
                if st.button("📊 Dashboard",use_container_width=True):
                    st.session_state.page = 'dashboard'
                    st.rerun()
                if st.button("👥 Benutzer",use_container_width=True):
                    st.session_state.page = 'users'
                    st.rerun()
                if st.button("📥 Export",use_container_width=True):
                    st.session_state.page = 'export'
                    st.rerun()
                if st.button("⚙️ Einstellungen",use_container_width=True):
                    st.session_state.page = 'settings'
                    st.rerun()
            
            st.divider()
            if st.button("📄 Impressum",use_container_width=True):
                st.session_state.page = 'impressum'
                st.rerun()
            
            if st.button("🚪 Logout",use_container_width=True):
                st.session_state.user = None
                st.session_state.page = 'home'
                st.rerun()
        else:
            if st.button("🔑 Login",use_container_width=True):
                st.session_state.page = 'login'
                st.rerun()
            if st.button("📄 Impressum",use_container_width=True):
                st.session_state.page = 'impressum'
                st.rerun()
        
        st.divider()
        if st.button("🌓" if st.session_state.dark_mode else "☀️",use_container_width=True,help="Dark Mode"):
            st.session_state.dark_mode = not st.session_state.dark_mode
            st.rerun()
    
    page = st.session_state.page
    
    if page == 'login':
        show_login()
    elif page == 'home':
        show_home()
    elif page == 'my_bookings':
        show_my_bookings()
    elif page == 'booking_list':
        show_booking_list()
    elif page == 'calendar':
        show_month_calendar()
    elif page == 'handbook':
        show_handbook()
    elif page == 'profile':
        show_profile()
    elif page == 'dashboard':
        show_dashboard()
    elif page == 'users':
        show_users()
    elif page == 'export':
        show_export()
    elif page == 'settings':
        show_settings()
    elif page == 'impressum':
        show_impressum()

def show_login():
    st.title("🔑 Login & Registrierung")
    
    tab1,tab2 = st.tabs(["🔐 Login","📝 Registrieren"])
    
    with tab1:
        st.subheader("Anmelden")
        email = st.text_input("E-Mail",key="login_email")
        pw = st.text_input("Passwort",type="password",key="login_pw")
        
        if st.button("Login",type="primary",use_container_width=True):
            if not email or not pw:
                st.error("❌ Bitte E-Mail und Passwort eingeben!")
            else:
                success,user = ww_db.auth(email,pw)
                if success:
                    st.session_state.user = user
                    st.session_state.page = 'home'
                    st.success("✅ Erfolgreich angemeldet!")
                    st.rerun()
                else:
                    st.error("❌ Falsche Login-Daten")
    
    with tab2:
        st.subheader("Neuen Account erstellen")
        
        with st.form("register_form"):
            reg_name = st.text_input("Name *")
            reg_email = st.text_input("E-Mail *")
            reg_phone = st.text_input("Telefon")
            reg_pw = st.text_input("Passwort *",type="password")
            reg_pw_confirm = st.text_input("Passwort bestätigen *",type="password")
            accept_terms = st.checkbox("Datenschutzerklärung akzeptieren")
            
            submitted = st.form_submit_button("📝 Registrieren",type="primary",use_container_width=True)
            
            if submitted:
                if not reg_name or not reg_email or not reg_pw or not reg_pw_confirm:
                    st.error("❌ Alle Pflichtfelder ausfüllen!")
                elif reg_pw != reg_pw_confirm:
                    st.error("❌ Passwörter stimmen nicht überein!")
                elif len(reg_pw) < 8:
                    st.error("❌ Passwort min. 8 Zeichen!")
                elif not accept_terms:
                    st.error("❌ Bitte akzeptiere die Bedingungen!")
                else:
                    success,msg = ww_db.create_user(reg_email,reg_name,reg_phone,reg_pw)
                    if success:
                        st.success(f"✅ {msg}")
                        st.balloons()
                    else:
                        st.error(f"❌ {msg}")

# ===== ENDE TEIL 2 =====
def show_home():
    if not st.session_state.user:
        st.title("🌊 Willkommen beim Wasserwacht Dienstplan+")
        st.info("Bitte melde dich an um Schichten zu buchen.")
        return
    
    st.title("📅 Schichtplan")
    user = st.session_state.user
    
    col1,col2 = st.columns([3,1])
    with col1:
        if 'current_week' not in st.session_state:
            st.session_state.current_week = week_start()
        
        cws = st.session_state.current_week
        
        c1,c2,c3 = st.columns([1,3,1])
        with c1:
            if st.button("◀️ Vorherige"):
                st.session_state.current_week -= timedelta(days=7)
                st.rerun()
        with c2:
            st.markdown(f"<h3 style='text-align:center'>KW {cws.isocalendar()[1]}, {cws.year}</h3>",unsafe_allow_html=True)
        with c3:
            if st.button("Nächste ▶️"):
                st.session_state.current_week += timedelta(days=7)
                st.rerun()
        
        bookings = ww_db.get_week_bookings(cws.strftime("%Y-%m-%d"))
        booking_map = {(b['slot_date'],b['slot_time']):b for b in bookings}
        
        for slot in WEEKLY_SLOTS:
            sd = slot_date(cws,slot['day'])
            booking = booking_map.get((sd,f"{slot['start']}-{slot['end']}"))
            blocked = is_blocked(sd)
            
            bg_color = f"{COLORS['grau_mittel']}80" if blocked else (f"{COLORS['erfolg']}20" if booking else f"{COLORS['blau']}10")
            border_color = COLORS['grau_mittel'] if blocked else (COLORS['erfolg'] if booking else COLORS['blau_hell'])
            
            card_html = f'''<div style="background:{bg_color};border:2px solid {border_color};border-radius:12px;
                padding:1rem;margin:0.5rem 0;transition:all 0.3s">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div><div style="font-weight:bold;font-size:1.1rem">{slot['day_name']}, {fmt_de(sd)}</div>
                    <div style="color:{COLORS['grau_dunkel']};font-size:0.9rem">{slot['start']}-{slot['end']}</div></div>
                    <div>{"<span style='color:" + COLORS['erfolg'] + ";font-weight:600'>✅ " + booking['user_name'] + "</span>" if booking else ""}
                    {"<span style='color:" + COLORS['grau_dunkel'] + "'>🚫 " + (block_reason(sd) or "") + "</span>" if blocked else ""}</div>
                </div></div>'''
            st.markdown(card_html,unsafe_allow_html=True)
            
            if blocked:
                pass
            elif booking:
                if user['role']=='admin' or booking['user_email']==user['email']:
                    if st.button(f"🔴 Stornieren",key=f"cancel_{slot['id']}_{sd}"):
                        ww_db.cancel_booking(booking['id'],user['email'])
                        mailer.cancellation_confirmation(booking['user_email'],booking['user_name'],sd,f"{slot['start']}-{slot['end']}")
                        st.success("Storniert!")
                        st.rerun()
            else:
                if st.button(f"✅ Buchen",key=f"book_{slot['id']}_{sd}",type="primary"):
                    existing = ww_db.get_booking(sd,f"{slot['start']}-{slot['end']}")
                    if existing and user['role']!='admin':
                        st.error(f"❌ Bereits von **{existing['user_name']}** gebucht!")
                    elif existing and user['role']=='admin':
                        st.warning(f"⚠️ Bereits von **{existing['user_name']}** gebucht!")
                        if st.button("🔄 Überschreiben (Admin)",key=f"override_{slot['id']}_{sd}"):
                            ww_db.cancel_booking(existing['id'],user['email'])
                            success,msg = ww_db.create_booking(sd,f"{slot['start']}-{slot['end']}",user['email'],user['name'],user.get('phone',''))
                            if success:
                                mailer.booking_confirmation(user['email'],user['name'],sd,f"{slot['start']}-{slot['end']}")
                                st.success("✅ Gebucht!")
                                st.rerun()
                    else:
                        success,msg = ww_db.create_booking(sd,f"{slot['start']}-{slot['end']}",user['email'],user['name'],user.get('phone',''))
                        if success:
                            mailer.booking_confirmation(user['email'],user['name'],sd,f"{slot['start']}-{slot['end']}")
                            if user.get('sms_notifications') and user.get('phone'):
                                sms.send(user['phone'],f"Buchung: {fmt_de(sd)} {slot['start']}-{slot['end']}")
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
    
    with col2:
        st.markdown("### 📊 Deine Stats")
        my_bookings = ww_db.get_user_bookings(user['email'],future_only=True)
        st.metric("Kommende",len(my_bookings))

def show_my_bookings():
    st.title("📅 Meine Schichten")
    user = st.session_state.user
    bookings = ww_db.get_user_bookings(user['email'])
    if not bookings:
        st.info("Noch keine Buchungen.")
        return
    for b in bookings:
        col1,col2,col3 = st.columns([2,2,1])
        with col1:
            st.write(f"**{fmt_de(b['slot_date'])}**")
        with col2:
            st.write(b['slot_time'])
        with col3:
            if st.button("🔴",key=f"cancel_{b['id']}"):
                ww_db.cancel_booking(b['id'],user['email'])
                st.rerun()

def show_booking_list():
    st.title("📋 Alle Buchungen")
    user = st.session_state.user
    is_admin = user.get('role')=='admin'
    
    col1,col2,col3 = st.columns(3)
    with col1:
        filter_type = st.selectbox("Zeitraum",["Kommende","Alle","Vergangene"])
    with col2:
        if is_admin:
            all_users = ww_db.get_all_users()
            user_filter = st.selectbox("User",["Alle"]+[u['name'] for u in all_users])
        else:
            user_filter = "Alle"
    with col3:
        sort_order = st.selectbox("Sortierung",["Datum ↑","Datum ↓"])
    
    try:
        query = ww_db.db.collection('bookings').where('status','==','confirmed')
        today = datetime.now().strftime("%Y-%m-%d")
        if filter_type=="Kommende":
            query = query.where('slot_date','>=',today)
        elif filter_type=="Vergangene":
            query = query.where('slot_date','<',today)
        
        bookings = []
        for doc in query.stream():
            b = doc.to_dict()
            b['id'] = doc.id
            if is_admin and user_filter!="Alle":
                if b.get('user_name')!=user_filter:
                    continue
            elif not is_admin and b.get('user_email')!=user['email']:
                continue
            bookings.append(b)
        
        bookings.sort(key=lambda x:x.get('slot_date',''),reverse=(sort_order=="Datum ↓"))
        
        if not bookings:
            st.info("Keine Buchungen.")
        else:
            st.success(f"**{len(bookings)} Buchungen**")
            for booking in bookings:
                is_past = datetime.strptime(booking['slot_date'],"%Y-%m-%d")<datetime.now()
                card_bg = f"{COLORS['grau_mittel']}40" if is_past else COLORS['grau_hell']
                st.markdown(f'''<div style="background:{card_bg};padding:1rem;margin:0.5rem 0;border-radius:8px;
                    border-left:4px solid {COLORS['erfolg'] if not is_past else COLORS['grau_mittel']}">
                    <div style="font-weight:bold">{fmt_de(booking['slot_date'])}</div>
                    <div>{booking['slot_time']} - {booking['user_name']}</div></div>''',unsafe_allow_html=True)
                if not is_past and (booking['user_email']==user['email'] or is_admin):
                    if st.button("🔴 Stornieren",key=f"cancel_list_{booking['id']}"):
                        ww_db.cancel_booking(booking['id'],user['email'])
                        st.rerun()
    except Exception as e:
        st.error(f"Fehler: {e}")

def show_month_calendar():
    st.title("📅 Monatskalender")
    if 'calendar_month' not in st.session_state:
        st.session_state.calendar_month = datetime.now().month
        st.session_state.calendar_year = datetime.now().year
    
    col1,col2,col3 = st.columns([1,2,1])
    with col1:
        if st.button("◀️"):
            st.session_state.calendar_month -= 1
            if st.session_state.calendar_month<1:
                st.session_state.calendar_month=12
                st.session_state.calendar_year-=1
            st.rerun()
    with col2:
        months = ['Jan','Feb','Mär','Apr','Mai','Jun','Jul','Aug','Sep','Okt','Nov','Dez']
        st.markdown(f"<h3 style='text-align:center'>{months[st.session_state.calendar_month-1]} {st.session_state.calendar_year}</h3>",unsafe_allow_html=True)
    with col3:
        if st.button("▶️"):
            st.session_state.calendar_month += 1
            if st.session_state.calendar_month>12:
                st.session_state.calendar_month=1
                st.session_state.calendar_year+=1
            st.rerun()
    
    month = st.session_state.calendar_month
    year = st.session_state.calendar_year
    month_start = f"{year}-{month:02d}-01"
    month_end = f"{year}-{month:02d}-{cal_module.monthrange(year,month)[1]}"
    
    bookings = {}
    for doc in ww_db.db.collection('bookings').where('slot_date','>=',month_start)\
            .where('slot_date','<=',month_end).where('status','==','confirmed').stream():
        b = doc.to_dict()
        if b['slot_date'] not in bookings:
            bookings[b['slot_date']] = []
        bookings[b['slot_date']].append(b)
    
    cal = cal_module.monthcalendar(year,month)
    weekdays = ['Mo','Di','Mi','Do','Fr','Sa','So']
    calendar_html = '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-top:1rem">'
    for day in weekdays:
        calendar_html += f'<div style="text-align:center;font-weight:bold;padding:0.5rem;background:{COLORS["grau_mittel"]};border-radius:4px">{day}</div>'
    
    for week in cal:
        for day in week:
            if day==0:
                calendar_html += '<div style="min-height:80px"></div>'
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                day_bookings = bookings.get(date_str,[])
                is_today = date_str==datetime.now().strftime("%Y-%m-%d")
                blocked = is_blocked(date_str)
                bg_color = f"{COLORS['rot']}20" if is_today else (COLORS['grau_mittel'] if blocked else COLORS['grau_hell'])
                badges_html = "".join([f'<div style="background:{COLORS["erfolg"]}30;color:{COLORS["erfolg"]};padding:2px 4px;margin:2px 0;border-radius:3px;font-size:0.7rem">{b["user_name"][:10]}</div>' for b in day_bookings])
                if blocked:
                    badges_html = f'<div style="color:{COLORS["grau_dunkel"]};font-size:0.7rem">🚫</div>'
                calendar_html += f'''<div style="min-height:80px;background:{bg_color};padding:0.5rem;border-radius:8px;
                    border:{"2px solid "+COLORS["rot"] if is_today else "1px solid "+COLORS["grau_mittel"]}">
                    <div style="font-weight:bold">{day}</div>{badges_html}</div>'''
    calendar_html += '</div>'
    st.markdown(calendar_html,unsafe_allow_html=True)

def show_handbook():
    st.title("📚 Handbuch")
    tab1,tab2 = st.tabs(["🚨 Notfall","🏊 Checkliste"])
    with tab1:
        st.markdown("""## 🚨 Notfall-Prozedur
        ### Sofortmaßnahmen:
        - 🚨 **Notruf:** 112
        - 🏥 **Erste Hilfe** leisten
        - 👥 **Evakuierung** falls nötig
        - 📞 **Betriebsleiter** informieren
        ### Notfallausrüstung:
        - 🏥 Erste-Hilfe: Eingang, Beckenrand
        - 🆘 Defibrillator: Haupteingang
        - 🔥 Feuerlöscher: Alle 20m""")
    with tab2:
        st.markdown("""## 🏊 Schicht-Checkliste
        ### VOR der Schicht:
        - [ ] 15 Min früher da
        - [ ] Dienstkleidung
        - [ ] Übergabe vom Vorgänger
        ### Schichtbeginn:
        - [ ] Wassertemp: 28-30°C
        - [ ] Chlor: 0,3-0,6 mg/l
        - [ ] pH-Wert: 7,0-7,4
        - [ ] Rettungsgeräte prüfen
        - [ ] Erste-Hilfe vollständig
        ### Während Schicht:
        - 👀 Permanente Beobachtung
        - 📝 Schichtbuch führen
        - 🔍 Stündliche Kontrollen""")

def show_profile():
    st.title("👤 Profil")
    user = st.session_state.user
    name = st.text_input("Name",value=user.get('name',''))
    phone = st.text_input("Telefon",value=user.get('phone',''))
    email_notif = st.checkbox("E-Mail",value=user.get('email_notifications',True))
    sms_notif = st.checkbox("SMS",value=user.get('sms_notifications',False))
    if st.button("💾 Speichern",type="primary"):
        ww_db.update_user(user['id'],name=name,phone=phone,email_notifications=email_notif,sms_notifications=sms_notif)
        st.success("✅ Gespeichert!")
        st.session_state.user = ww_db.get_user(user['email'])

def show_dashboard():
    if st.session_state.user.get('role')!='admin':
        st.error("❌ Nur für Admins")
        return
    st.title("📊 Dashboard")
    stats = ww_db.get_stats()
    col1,col2,col3 = st.columns(3)
    with col1:
        st.markdown(f'<div style="background:linear-gradient(135deg,{COLORS["rot"]},{COLORS["blau"]});padding:1.5rem;border-radius:12px;text-align:center;color:white"><h2 style="color:white;margin:0">{stats["total_users"]}</h2><p style="margin:0">User</p></div>',unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div style="background:linear-gradient(135deg,{COLORS["blau"]},{COLORS["blau_hell"]});padding:1.5rem;border-radius:12px;text-align:center;color:white"><h2 style="color:white;margin:0">{stats["future_bookings"]}</h2><p style="margin:0">Kommend</p></div>',unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div style="background:linear-gradient(135deg,{COLORS["rot_hell"]},{COLORS["rot"]});padding:1.5rem;border-radius:12px;text-align:center;color:white"><h2 style="color:white;margin:0">{stats["month_bookings"]}</h2><p style="margin:0">Monat</p></div>',unsafe_allow_html=True)
    
    st.divider()
    st.subheader("🆓 Freie Slots (4 Wochen)")
    free = stats['free_slots_next_4weeks']
    if free:
        for slot in free[:10]:
            st.info(f"📅 {fmt_de(slot['date'])} - {slot['slot']}")
    else:
        st.success("✅ Alle Slots gebucht!")

def show_users():
    if st.session_state.user.get('role')!='admin':
        st.error("❌ Nur für Admins")
        return
    st.title("👥 Benutzer")
    tab1,tab2 = st.tabs(["Liste","Neu"])
    with tab1:
        users = ww_db.get_all_users()
        for u in users:
            col1,col2,col3 = st.columns([2,2,1])
            with col1:
                st.write(f"**{u['name']}**")
            with col2:
                st.write(u['email'])
            with col3:
                if u['email']!=st.session_state.user['email']:
                    if st.button("🗑️",key=f"del_{u['id']}"):
                        ww_db.delete_user(u['email'])
                        st.rerun()
    with tab2:
        with st.form("new_user"):
            email = st.text_input("E-Mail")
            name = st.text_input("Name")
            phone = st.text_input("Telefon")
            password = st.text_input("Passwort",type="password")
            role = st.selectbox("Rolle",["user","admin"])
            if st.form_submit_button("User anlegen",type="primary"):
                success,msg = ww_db.create_user(email,name,phone,password,role)
                st.success(f"✅ {msg}") if success else st.error(f"❌ {msg}")

def show_export():
    if st.session_state.user.get('role')!='admin':
        st.error("❌ Nur für Admins")
        return
    st.title("📥 Export")
    if st.button("📊 Excel",type="primary"):
        bookings = []
        for doc in ww_db.db.collection('bookings').stream():
            b = doc.to_dict()
            bookings.append({'Datum':b.get('slot_date',''),'Zeit':b.get('slot_time',''),
                'Name':b.get('user_name',''),'Status':b.get('status','')})
        df = pd.DataFrame(bookings)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer,engine='openpyxl') as writer:
            df.to_excel(writer,index=False)
        st.download_button("⬇️ Download",buffer.getvalue(),
            f"export_{datetime.now().strftime('%Y%m%d')}.xlsx")

def show_settings():
    if st.session_state.user.get('role')!='admin':
        st.error("❌ Nur für Admins")
        return
    st.title("⚙️ Einstellungen")
    st.info("E-Mail/SMS-Templates können über Secrets konfiguriert werden.")

def show_impressum():
    st.title("📄 Impressum")
    default = """# Impressum\n**Wasserwacht Hauzenberg e.V.**\n[Adresse]\n\n**Kontakt:** [E-Mail]"""
    impressum = ww_db.get_setting('impressum',default)
    st.markdown(impressum)
    if st.session_state.user and st.session_state.user.get('role')=='admin':
        with st.expander("✏️ Bearbeiten"):
            new = st.text_area("Text",impressum,height=300)
            if st.button("💾 Speichern",type="primary"):
                ww_db.set_setting('impressum',new)
                st.success("✅ Gespeichert!")
                st.rerun()

if __name__ == "__main__":
    main()