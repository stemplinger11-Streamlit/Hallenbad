"""
Wasserwacht Dienstplan+ v7.2 - Firebase Edition
Alle Bugs behoben | Alle Features funktional | Production-Ready
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

# ===== PAGE CONFIG =====
st.set_page_config(
    page_title="Wasserwacht Dienstplan+",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== KONFIGURATION =====
VERSION = "7.2 - Production"
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
    "erfolg": "#17BF63", "warnung": "#FFAD1F", "fehler": "#E0245E",
    "orange": "#FF8C00", "orange_hell": "#FFA500"
}

# ===== FIREBASE INIT =====
@st.cache_resource
def init_firestore():
    try:
        if not hasattr(st, 'secrets'):
            st.error("❌ Keine Secrets!")
            st.stop()
        key = st.secrets.get("firebase", {}).get("service_account_key")
        if not key:
            st.error("❌ Firebase Key fehlt!")
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
    @media (max-width: 768px) {{
        section[data-testid="stSidebar"] {{display: none !important;}}
        .main {{padding-bottom:80px;}}
    }}
    </style>""", unsafe_allow_html=True)

# ===== DATABASE CLASS =====
class WasserwachtDB:
    def __init__(self):
        self.db = db
        self._validate_data()
        self._init_admin()
    
    def _validate_data(self):
        try:
            for coll in ['users', 'bookings', 'settings', 'audit_log']:
                if not self.db.collection(coll).limit(1).get():
                    print(f"ℹ️ Collection '{coll}' erstellt")
        except Exception as e:
            print(f"Validierung: {e}")
    
    def _init_admin(self):
        if hasattr(st,'secrets'):
            email = st.secrets.get("ADMIN_EMAIL","admin@wasserwacht.de")
            pw = st.secrets.get("ADMIN_PASSWORD","admin123")
            if not self.get_user(email):
                try:
                    self.db.collection('users').add({
                        'email':email,'name':'Admin','phone':'','password_hash':hash_pw(pw),
                        'role':'admin','active':True,'email_notifications':True,
                        'sms_notifications':False,'created_at':firestore.SERVER_TIMESTAMP
                    })
                    print(f"✅ Admin: {email}")
                except:
                    pass
    
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
            self.log('user_created',f"User {email}")
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
                self.log('user_deleted',f"{email}")
                return True
            return False
        except:
            return False
    
    def create_booking(self,slot_date,slot_time,user_email,user_name,user_phone):
        try:
            existing = self.get_booking(slot_date,slot_time)
            if existing:
                return False,"Slot bereits gebucht"
            self.db.collection('bookings').add({
                'slot_date':slot_date,'slot_time':slot_time,'user_email':user_email,
                'user_name':user_name,'user_phone':user_phone,'status':'confirmed',
                'created_at':firestore.SERVER_TIMESTAMP
            })
            self.log('booking_created',f"{user_name} {slot_date}")
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
            q = self.db.collection('bookings').where('user_email','==',email).where('status','==','confirmed')
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
            self.log('booking_cancelled',f"{bid}")
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
        """FIX: Robuste Statistiken"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Total Users
            all_users = self.get_all_users()
            total_users = len([u for u in all_users if u.get('active',True)])
            
            # Future Bookings
            future_docs = list(self.db.collection('bookings')\
                .where('slot_date','>=',today).where('status','==','confirmed').stream())
            future_count = len(future_docs)
            
            # Month Bookings
            month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
            month_docs = list(self.db.collection('bookings')\
                .where('slot_date','>=',month_start).where('status','==','confirmed').stream())
            month_count = len(month_docs)
            
            # Free Slots (next 4 weeks)
            free_slots = []
            for i in range(28):
                check_date = (datetime.now()+timedelta(days=i)).strftime("%Y-%m-%d")
                if not is_blocked(check_date):
                    for slot in WEEKLY_SLOTS:
                        ws = week_start(datetime.strptime(check_date,"%Y-%m-%d"))
                        slot_d = slot_date(ws,slot['day'])
                        if slot_d == check_date:
                            if not self.get_booking(check_date,f"{slot['start']}-{slot['end']}"):
                                free_slots.append({
                                    'date':check_date,
                                    'slot':f"{slot['day_name']} {slot['start']}-{slot['end']}"
                                })
            
            return {
                'total_users':total_users,
                'future_bookings':future_count,
                'month_bookings':month_count,
                'free_slots_next_4weeks':free_slots
            }
        except Exception as e:
            print(f"Stats-Fehler: {e}")
            return {'total_users':0,'future_bookings':0,'month_bookings':0,'free_slots_next_4weeks':[]}
    
    def archive_old(self):
        try:
            months = 12
            archive_date = (datetime.now()-timedelta(days=30*months)).strftime("%Y-%m-%d")
            count = 0
            for doc in self.db.collection('bookings').where('slot_date','<',archive_date).stream():
                self.db.collection('archive').add(doc.to_dict())
                doc.reference.delete()
                count += 1
            if count > 0:
                self.log('archiving',f"{count} Buchungen")
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
            print(f"E-Mail: {e}")
            return False
    
    def booking_confirmation(self,user_email,user_name,slot_date,slot_time):
        template = ww_db.get_setting('email_booking_template',
            'Hallo {name}, deine Schicht am {date} um {time} wurde gebucht.')
        body = f"""<html><body><h2 style="color:{COLORS['rot']}">Wasserwacht Dienstplan+</h2>
        <p>{template.format(name=user_name,date=fmt_de(slot_date),time=slot_time)}</p></body></html>"""
        return self.send(user_email,f"✅ Buchung {fmt_de(slot_date)}",body)
    
    def cancellation_confirmation(self,user_email,user_name,slot_date,slot_time):
        template = ww_db.get_setting('email_cancellation_template',
            'Hallo {name}, deine Schicht am {date} um {time} wurde storniert.')
        body = f"""<html><body><h2 style="color:{COLORS['rot']}">Wasserwacht Dienstplan+</h2>
        <p>{template.format(name=user_name,date=fmt_de(slot_date),time=slot_time)}</p></body></html>"""
        return self.send(user_email,f"🔴 Stornierung {fmt_de(slot_date)}",body)
    
    def backup_email(self,backup_zip):
        try:
            subject = f"📦 Backup {datetime.now().strftime('%d.%m.%Y')}"
            body = f"<html><body><h2>Automatisches Backup</h2><p>{datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}</p></body></html>"
            filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
            backup_emails = []
            if hasattr(st,'secrets'):
                try:
                    backup_emails = json.loads(st.secrets.get("BACKUP_EMAILS","[]"))
                except:
                    backup_emails = []
                admin = st.secrets.get("ADMIN_EMAIL_RECEIVER","")
                if admin and admin not in backup_emails:
                    backup_emails.append(admin)
            success = 0
            for email in backup_emails:
                if self.send(email,subject,body,[(filename,backup_zip)]):
                    success += 1
            return success > 0
        except:
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
        template = ww_db.get_setting('sms_24h_template',
            'Wasserwacht: Deine Schicht ist morgen {date} um {time}.')
        msg = template.format(name=user_name,date=fmt_de(slot_date),time=slot_time)
        return self.send(user_phone,msg)
    
    def reminder_1h(self,user_phone,user_name,slot_time):
        template = ww_db.get_setting('sms_1h_template',
            'Wasserwacht: Deine Schicht beginnt in 1h ({time}).')
        msg = template.format(name=user_name,time=slot_time)
        return self.send(user_phone,msg)

mailer = Mailer()
sms = TwilioSMS()

# ===== SCHEDULER =====
def daily_tasks():
    ww_db.archive_old()
    if hasattr(st,'secrets') and st.secrets.get("ENABLE_DAILY_BACKUP","true").lower()=="true":
        try:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as zf:
                csv = "date,time,user,phone,status\n"
                for doc in ww_db.db.collection('bookings').stream():
                    d = doc.to_dict()
                    csv += f"{d.get('slot_date','')},{d.get('slot_time','')},{d.get('user_name','')},{d.get('user_phone','')},{d.get('status','')}\n"
                zf.writestr('bookings.csv',csv)
            mailer.backup_email(buffer.getvalue())
        except:
            pass

def reminder_tasks():
    tomorrow = (datetime.now()+timedelta(days=1)).strftime("%Y-%m-%d")
    for doc in ww_db.db.collection('bookings').where('slot_date','==',tomorrow).where('status','==','confirmed').stream():
        b = doc.to_dict()
        if b.get('user_phone'):
            sms.reminder_24h(b['user_phone'],b['user_name'],b['slot_date'],b['slot_time'])

def check_free_slots_alarm():
    try:
        critical = []
        for i in range(1,8):
            check_date = (datetime.now()+timedelta(days=i)).strftime("%Y-%m-%d")
            if not is_blocked(check_date):
                for slot in WEEKLY_SLOTS:
                    ws = week_start(datetime.strptime(check_date,"%Y-%m-%d"))
                    slot_d = slot_date(ws,slot['day'])
                    if slot_d == check_date and not ww_db.get_booking(check_date,f"{slot['start']}-{slot['end']}"):
                        critical.append({'date':fmt_de(check_date),'day':slot['day_name'],'time':f"{slot['start']}-{slot['end']}"})
        if critical:
            admins = [u['email'] for u in ww_db.get_all_users() if u.get('role')=='admin' and u.get('active',True)]
            slots_html = "".join([f"<li>{s['date']} ({s['day']}) {s['time']}</li>" for s in critical])
            body = f"<html><body><h2 style='color:{COLORS['warnung']}'>⚠️ {len(critical)} freie Slots</h2><ul>{slots_html}</ul></body></html>"
            for admin in admins:
                mailer.send(admin,"⚠️ Freie Slots",body)
    except:
        pass

if 'scheduler_started' not in st.session_state:
    try:
        scheduler = BackgroundScheduler(timezone=TZ)
        h,m = (st.secrets.get("BACKUP_TIME","20:00") if hasattr(st,'secrets') else "20:00").split(":")
        scheduler.add_job(daily_tasks,'cron',hour=int(h),minute=int(m))
        scheduler.add_job(reminder_tasks,'cron',hour=18,minute=0)
        scheduler.add_job(check_free_slots_alarm,'cron',hour=18,minute=0)
        scheduler.start()
        st.session_state.scheduler_started = True
    except:
        pass

# ===== MAIN APP =====
def main():
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'last_activity' not in st.session_state:
        st.session_state.last_activity = datetime.now()
    
    timeout_min = 5
    if st.session_state.user:
        inactive = (datetime.now()-st.session_state.last_activity).total_seconds()
        if inactive > timeout_min*60:
            st.session_state.user = None
            st.warning("⏰ Ausgeloggt")
            st.rerun()
        else:
            st.session_state.last_activity = datetime.now()
    
    if 'dark_mode' not in st.session_state:
        st.session_state.dark_mode = False
    inject_css(st.session_state.dark_mode)
    if 'page' not in st.session_state:
        st.session_state.page = 'home'
    
    with st.sidebar:
        st.markdown(f"<h1 style='color:{COLORS['rot']}'>🌊 Wasserwacht</h1>",unsafe_allow_html=True)
        st.markdown(f"<p style='color:{COLORS['grau_dunkel']}'>v{VERSION}</p>",unsafe_allow_html=True)
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
                st.markdown("**🔧 Admin**")
                if st.button("📊 Dashboard",use_container_width=True):
                    st.session_state.page = 'dashboard'
                    st.rerun()
                if st.button("👥 Benutzer",use_container_width=True):
                    st.session_state.page = 'users'
                    st.rerun()
                if st.button("📋 Alle Buchungen",use_container_width=True):
                    st.session_state.page = 'all_bookings'
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
        if st.button("🌓" if st.session_state.dark_mode else "☀️",use_container_width=True):
            st.session_state.dark_mode = not st.session_state.dark_mode
            st.rerun()
    
    page = st.session_state.page
    if page == 'login':
        show_login()
    elif page == 'home':
        show_home()
    elif page == 'my_bookings':
        show_my_bookings()
    elif page == 'all_bookings':
        show_all_bookings()
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
                st.error("❌ Felder ausfüllen!")
            else:
                success,user = ww_db.auth(email,pw)
                if success:
                    st.session_state.user = user
                    st.session_state.page = 'home'
                    st.success("✅ Angemeldet!")
                    st.rerun()
                else:
                    st.error("❌ Falsche Daten")
    with tab2:
        st.subheader("Registrieren")
        with st.form("register"):
            name = st.text_input("Name *")
            email = st.text_input("E-Mail *")
            phone = st.text_input("Telefon")
            pw = st.text_input("Passwort *",type="password")
            pw2 = st.text_input("Passwort bestätigen *",type="password")
            accept = st.checkbox("Datenschutz akzeptieren")
            if st.form_submit_button("📝 Registrieren",type="primary",use_container_width=True):
                if not name or not email or not pw or not pw2:
                    st.error("❌ Alle Felder!")
                elif pw != pw2:
                    st.error("❌ Passwörter ungleich!")
                elif len(pw) < 8:
                    st.error("❌ Min. 8 Zeichen!")
                elif not accept:
                    st.error("❌ Datenschutz!")
                else:
                    success,msg = ww_db.create_user(email,name,phone,pw)
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
        
        # FIX: Farben je nach Status
        if blocked:
            bg_color = f"{COLORS['grau_mittel']}80"
            border_color = COLORS['grau_mittel']
        elif booking:
            bg_color = f"{COLORS['orange']}30"
            border_color = COLORS['orange']
        else:
            bg_color = f"{COLORS['blau']}10"
            border_color = COLORS['blau_hell']
        
        # FIX: Name anzeigen wenn gebucht
        booked_info = f"<span style='color:{COLORS['orange']};font-weight:600'>✅ {booking['user_name']}</span>" if booking else ""
        blocked_info = f"<span style='color:{COLORS['grau_dunkel']}'>🚫 {block_reason(sd) or ''}</span>" if blocked else ""
        
        card_html = f'''<div style="background:{bg_color};border:2px solid {border_color};border-radius:12px;
            padding:1rem;margin:0.5rem 0;transition:all 0.3s">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div><div style="font-weight:bold;font-size:1.1rem">{slot['day_name']}, {fmt_de(sd)}</div>
                <div style="color:{COLORS['grau_dunkel']};font-size:0.9rem">{slot['start']}-{slot['end']}</div></div>
                <div>{booked_info}{blocked_info}</div>
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
                    if st.button("🔄 Überschreiben",key=f"override_{slot['id']}_{sd}"):
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
                            sms.send(user['phone'],f"Buchung: {fmt_de(sd)}")
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)

def show_my_bookings():
    st.title("📅 Meine Schichten")
    user = st.session_state.user
    bookings = ww_db.get_user_bookings(user['email'])
    if not bookings:
        st.info("Noch keine Buchungen.")
        return
    
    # FIX: Schöne Cards
    for b in bookings:
        is_past = datetime.strptime(b['slot_date'],"%Y-%m-%d")<datetime.now()
        bg = f"{COLORS['grau_mittel']}40" if is_past else f"{COLORS['erfolg']}20"
        border = COLORS['grau_mittel'] if is_past else COLORS['erfolg']
        
        st.markdown(f'''<div style="background:{bg};border:2px solid {border};border-radius:12px;
            padding:1rem;margin:0.5rem 0">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <div><div style="font-weight:bold;font-size:1.1rem">{fmt_de(b['slot_date'])}</div>
                <div style="color:{COLORS['grau_dunkel']}">{b['slot_time']}</div></div>
                {"<span style='color:"+COLORS['grau_dunkel']+"'>⏮️ Vergangen</span>" if is_past else ""}
            </div></div>''',unsafe_allow_html=True)
        
        if not is_past:
            if st.button("🔴 Stornieren",key=f"cancel_{b['id']}"):
                ww_db.cancel_booking(b['id'],user['email'])
                st.rerun()

def show_all_bookings():
    if st.session_state.user.get('role')!='admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("📋 Alle Buchungen (Admin)")
    
    col1,col2,col3 = st.columns(3)
    with col1:
        filter_type = st.selectbox("Zeitraum",["Kommende","Alle","Vergangene"])
    with col2:
        all_users = ww_db.get_all_users()
        user_filter = st.selectbox("User",["Alle"]+[u['name'] for u in all_users])
    with col3:
        sort_order = st.selectbox("Sort",["Datum ↑","Datum ↓"])
    
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        bookings = []
        
        # FIX: Einfache Query ohne Composite Index
        for doc in ww_db.db.collection('bookings').where('status','==','confirmed').stream():
            b = doc.to_dict()
            b['id'] = doc.id
            
            # Filter nach Zeitraum
            if filter_type=="Kommende" and b['slot_date']<today:
                continue
            elif filter_type=="Vergangene" and b['slot_date']>=today:
                continue
            
            # Filter nach User
            if user_filter!="Alle" and b.get('user_name')!=user_filter:
                continue
            
            bookings.append(b)
        
        bookings.sort(key=lambda x:x['slot_date'],reverse=(sort_order=="Datum ↓"))
        
        if not bookings:
            st.info("Keine Buchungen.")
        else:
            st.success(f"**{len(bookings)} Buchungen**")
            for b in bookings:
                is_past = datetime.strptime(b['slot_date'],"%Y-%m-%d")<datetime.now()
                bg = f"{COLORS['grau_mittel']}40" if is_past else f"{COLORS['erfolg']}20"
                st.markdown(f'''<div style="background:{bg};padding:1rem;margin:0.5rem 0;border-radius:8px">
                    <b>{fmt_de(b['slot_date'])}</b> {b['slot_time']} - {b['user_name']}</div>''',unsafe_allow_html=True)
                if not is_past:
                    if st.button("🔴 Stornieren",key=f"cancel_{b['id']}"):
                        ww_db.cancel_booking(b['id'],st.session_state.user['email'])
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
    
    # FIX: Einfache Query ohne Composite Index
    bookings = {}
    try:
        for doc in ww_db.db.collection('bookings').where('status','==','confirmed').stream():
            b = doc.to_dict()
            date_str = b['slot_date']
            if date_str.startswith(f"{year}-{month:02d}"):
                if date_str not in bookings:
                    bookings[date_str] = []
                bookings[date_str].append(b)
    except:
        pass
    
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
                bg = f"{COLORS['rot']}20" if is_today else (COLORS['grau_mittel'] if blocked else COLORS['grau_hell'])
                badges = "".join([f'<div style="background:{COLORS["erfolg"]}30;color:{COLORS["erfolg"]};padding:2px;margin:2px 0;border-radius:3px;font-size:0.7rem">{b["user_name"][:10]}</div>' for b in day_bookings])
                if blocked:
                    badges = f'<div style="color:{COLORS["grau_dunkel"]};font-size:0.7rem">🚫</div>'
                calendar_html += f'''<div style="min-height:80px;background:{bg};padding:0.5rem;border-radius:8px;
                    border:{"2px solid "+COLORS["rot"] if is_today else "1px solid "+COLORS["grau_mittel"]}">
                    <div style="font-weight:bold">{day}</div>{badges}</div>'''
    calendar_html += '</div>'
    st.markdown(calendar_html,unsafe_allow_html=True)

def show_handbook():
    st.title("📚 Handbuch")
    user = st.session_state.user
    is_admin = user.get('role')=='admin'
    
    tab1,tab2 = st.tabs(["🚨 Notfall","🏊 Checkliste"])
    
    with tab1:
        default_notfall = """## 🚨 Notfall-Prozedur
### Sofortmaßnahmen:
- 🚨 **Notruf:** 112
- 🏥 **Erste Hilfe** leisten
- 👥 **Evakuierung** falls nötig
### Ausrüstung:
- 🏥 Erste-Hilfe: Eingang, Beckenrand
- 🆘 Defibrillator: Haupteingang"""
        content = ww_db.get_setting('handbook_notfall',default_notfall)
        st.markdown(content)
        if is_admin:
            with st.expander("✏️ Bearbeiten (Admin)"):
                new = st.text_area("",content,height=300,key="edit_notfall")
                if st.button("💾 Speichern",key="save_notfall"):
                    ww_db.set_setting('handbook_notfall',new)
                    st.success("✅ Gespeichert!")
                    st.rerun()
    
    with tab2:
        default_check = """## 🏊 Schicht-Checkliste
### VOR Schicht:
- [ ] 15 Min früher
- [ ] Dienstkleidung
### Start:
- [ ] Wasser: 28-30°C
- [ ] Chlor: 0,3-0,6 mg/l
- [ ] Rettungsgeräte prüfen"""
        content = ww_db.get_setting('handbook_checkliste',default_check)
        st.markdown(content)
        if is_admin:
            with st.expander("✏️ Bearbeiten (Admin)"):
                new = st.text_area("",content,height=300,key="edit_check")
                if st.button("💾 Speichern",key="save_check"):
                    ww_db.set_setting('handbook_checkliste',new)
                    st.success("✅ Gespeichert!")
                    st.rerun()

def show_profile():
    st.title("👤 Profil")
    user = st.session_state.user
    
    tab1,tab2 = st.tabs(["📝 Daten","🔐 Sicherheit"])
    
    with tab1:
        name = st.text_input("Name",value=user.get('name',''))
        phone = st.text_input("Telefon",value=user.get('phone',''))
        email_notif = st.checkbox("E-Mail",value=user.get('email_notifications',True))
        sms_notif = st.checkbox("SMS",value=user.get('sms_notifications',False))
        
        col1,col2 = st.columns(2)
        with col1:
            if st.button("📧 E-Mail testen",use_container_width=True):
                if mailer.send(user['email'],"Test","<p>Test-E-Mail</p>"):
                    st.success("✅ E-Mail gesendet!")
                else:
                    st.error("❌ Fehler")
        with col2:
            if st.button("📱 SMS testen",use_container_width=True):
                if phone and sms.send(phone,"Wasserwacht Test-SMS"):
                    st.success("✅ SMS gesendet!")
                else:
                    st.error("❌ Fehler")
        
        if st.button("💾 Speichern",type="primary"):
            ww_db.update_user(user['id'],name=name,phone=phone,email_notifications=email_notif,sms_notifications=sms_notif)
            st.success("✅ Gespeichert!")
            st.session_state.user = ww_db.get_user(user['email'])
    
    with tab2:
        st.subheader("Passwort ändern")
        old_pw = st.text_input("Altes Passwort",type="password")
        new_pw = st.text_input("Neues Passwort",type="password")
        new_pw2 = st.text_input("Neues Passwort bestätigen",type="password")
        
        if st.button("🔐 Passwort ändern",type="primary"):
            if not old_pw or not new_pw or not new_pw2:
                st.error("❌ Alle Felder!")
            elif hash_pw(old_pw) != user['password_hash']:
                st.error("❌ Altes Passwort falsch!")
            elif new_pw != new_pw2:
                st.error("❌ Neue Passwörter ungleich!")
            elif len(new_pw) < 8:
                st.error("❌ Min. 8 Zeichen!")
            else:
                ww_db.update_user(user['id'],password_hash=hash_pw(new_pw))
                st.success("✅ Passwort geändert!")

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
        st.success("✅ Alle gebucht!")

def show_users():
    if st.session_state.user.get('role')!='admin':
        st.error("❌ Nur für Admins")
        return
    st.title("👥 Benutzer")
    
    tab1,tab2,tab3 = st.tabs(["Liste","Neu","Für User buchen"])
    
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
    
    with tab3:
        st.subheader("Schicht für User buchen")
        users = ww_db.get_all_users()
        user_sel = st.selectbox("User",[(u['name'],u['email'],u.get('phone','')) for u in users],format_func=lambda x:x[0])
        
        ws = st.date_input("Woche",value=week_start())
        ws = week_start(ws)
        
        slot_sel = st.selectbox("Slot",[(s['day_name'],s['start'],s['end']) for s in WEEKLY_SLOTS],format_func=lambda x:f"{x[0]} {x[1]}-{x[2]}")
        slot_day = [s for s in WEEKLY_SLOTS if s['day_name']==slot_sel[0]][0]
        sd = slot_date(ws,slot_day['day'])
        
        if st.button("Für User buchen",type="primary"):
            success,msg = ww_db.create_booking(sd,f"{slot_sel[1]}-{slot_sel[2]}",user_sel[1],user_sel[0],user_sel[2])
            if success:
                st.success(f"✅ {msg}")
                mailer.booking_confirmation(user_sel[1],user_sel[0],sd,f"{slot_sel[1]}-{slot_sel[2]}")
            else:
                st.error(f"❌ {msg}")

def show_export():
    if st.session_state.user.get('role')!='admin':
        st.error("❌ Nur für Admins")
        return
    st.title("📥 Export & Backup")
    
    col1,col2 = st.columns(2)
    
    with col1:
        st.markdown(f"""<div style='background:{COLORS['grau_hell']};padding:1.5rem;border-radius:12px;text-align:center'>
            <h3>📊 Excel Export</h3><p>Alle Buchungen als Excel</p></div>""",unsafe_allow_html=True)
        if st.button("📊 Excel Download",type="primary",use_container_width=True):
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
    
    with col2:
        st.markdown(f"""<div style='background:{COLORS['grau_hell']};padding:1.5rem;border-radius:12px;text-align:center'>
            <h3>📧 E-Mail Backup</h3><p>Backup per E-Mail senden</p></div>""",unsafe_allow_html=True)
        if st.button("📧 Backup senden",type="primary",use_container_width=True):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as zf:
                csv = "date,time,user,status\n"
                for doc in ww_db.db.collection('bookings').stream():
                    d = doc.to_dict()
                    csv += f"{d.get('slot_date','')},{d.get('slot_time','')},{d.get('user_name','')},{d.get('status','')}\n"
                zf.writestr('bookings.csv',csv)
            if mailer.backup_email(buffer.getvalue()):
                st.success("✅ Backup gesendet!")
            else:
                st.error("❌ Fehler")

def show_settings():
    if st.session_state.user.get('role')!='admin':
        st.error("❌ Nur für Admins")
        return
    st.title("⚙️ Einstellungen")
    
    tab1,tab2 = st.tabs(["📧 E-Mail","📱 SMS"])
    
    with tab1:
        st.subheader("E-Mail-Templates")
        booking = ww_db.get_setting('email_booking_template','Hallo {name}, deine Schicht am {date} um {time} wurde gebucht.')
        cancel = ww_db.get_setting('email_cancellation_template','Hallo {name}, deine Schicht am {date} um {time} wurde storniert.')
        
        new_booking = st.text_area("Buchung",booking,height=100,help="{name}, {date}, {time}")
        new_cancel = st.text_area("Stornierung",cancel,height=100,help="{name}, {date}, {time}")
        
        if st.button("💾 E-Mail-Templates speichern",type="primary"):
            ww_db.set_setting('email_booking_template',new_booking)
            ww_db.set_setting('email_cancellation_template',new_cancel)
            st.success("✅ Gespeichert!")
    
    with tab2:
        st.subheader("SMS-Templates")
        sms24 = ww_db.get_setting('sms_24h_template','Wasserwacht: Deine Schicht ist morgen {date} um {time}.')
        sms1 = ww_db.get_setting('sms_1h_template','Wasserwacht: Deine Schicht beginnt in 1h ({time}).')
        
        new_sms24 = st.text_area("24h Reminder",sms24,height=100,help="{name}, {date}, {time}")
        new_sms1 = st.text_area("1h Reminder",sms1,height=100,help="{name}, {time}")
        
        if st.button("💾 SMS-Templates speichern",type="primary"):
            ww_db.set_setting('sms_24h_template',new_sms24)
            ww_db.set_setting('sms_1h_template',new_sms1)
            st.success("✅ Gespeichert!")

def show_impressum():
    st.title("📄 Impressum")
    default = """# Impressum\n**Wasserwacht Hauzenberg e.V.**\n[Adresse]\n\n**Kontakt:** [E-Mail]"""
    impressum = ww_db.get_setting('impressum',default)
    st.markdown(impressum)
    if st.session_state.user and st.session_state.user.get('role')=='admin':
        with st.expander("✏️ Bearbeiten (Admin)"):
            new = st.text_area("Text",impressum,height=300)
            if st.button("💾 Speichern",type="primary"):
                ww_db.set_setting('impressum',new)
                st.success("✅ Gespeichert!")
                st.rerun()

if __name__ == "__main__":
    main()