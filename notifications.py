"""
Wasserwacht Dienstplan+ - Notification System
Verbesserte SMS & E-Mail Funktionen mit detailliertem Error-Handling
"""

import streamlit as st
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import email.utils
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from datetime import datetime
import pytz

TZ = pytz.timezone("Europe/Berlin")

# ===== E-MAIL KLASSE MIT DETAILLIERTEM LOGGING =====
class EmailNotifier:
    """Verbesserte E-Mail-Klasse mit detailliertem Error-Handling"""
    
    def __init__(self):
        if hasattr(st, 'secrets'):
            self.server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
            self.port = int(st.secrets.get("SMTP_PORT", 587))
            self.user = st.secrets.get("SMTP_USER", "")
            self.password = st.secrets.get("SMTP_PASSWORD", "")
            self.admin_receiver = st.secrets.get("ADMIN_EMAIL_RECEIVER", "")
            self.from_name = "Wasserwacht Dienstplan"
        else:
            raise ValueError("❌ Streamlit Secrets nicht gefunden!")
        
        # Validierung
        if not self.user or not self.password:
            raise ValueError("❌ SMTP_USER oder SMTP_PASSWORD fehlt in Secrets!")
    
    def send_email(self, to, subject, body_html, attachments=None):
        """
        E-Mail senden mit detailliertem Error-Handling
        
        Args:
            to: Empfänger E-Mail
            subject: Betreff
            body_html: HTML-Body
            attachments: Liste von (filename, data) Tupeln
            
        Returns:
            (success: bool, message: str)
        """
        try:
            # MIMEMultipart erstellen
            msg = MIMEMultipart('alternative')
            msg['From'] = email.utils.formataddr((self.from_name, self.user))
            msg['To'] = to
            msg['Subject'] = subject
            msg['Date'] = email.utils.formatdate(localtime=True)
            
            # HTML Body
            html_part = MIMEText(body_html, 'html', 'utf-8')
            msg.attach(html_part)
            
            # Anhänge
            if attachments:
                for filename, data in attachments:
                    part = MIMEBase('application', 'octet-stream')
                    if isinstance(data, bytes):
                        part.set_payload(data)
                    else:
                        part.set_payload(data.encode('utf-8'))
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename={filename}')
                    msg.attach(part)
            
            # SMTP Verbindung
            with smtplib.SMTP(self.server, self.port, timeout=30) as server:
                server.set_debuglevel(0)  # 1 für Debug-Output
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.user, self.password)
                server.send_message(msg)
            
            success_msg = f"✅ E-Mail erfolgreich gesendet an {to}"
            print(success_msg)
            return True, success_msg
            
        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"❌ SMTP Authentifizierung fehlgeschlagen: {str(e)}"
            print(error_msg)
            return False, "SMTP Auth-Fehler! Prüfe SMTP_USER und SMTP_PASSWORD (Gmail: App-Passwort verwenden!)"
            
        except smtplib.SMTPRecipientsRefused as e:
            error_msg = f"❌ Empfänger abgelehnt: {str(e)}"
            print(error_msg)
            return False, f"Empfänger-Adresse ungültig: {to}"
            
        except smtplib.SMTPException as e:
            error_msg = f"❌ SMTP Fehler: {str(e)}"
            print(error_msg)
            return False, f"SMTP-Fehler: {str(e)}"
            
        except Exception as e:
            error_msg = f"❌ Unerwarteter E-Mail Fehler: {str(e)}"
            print(error_msg)
            return False, f"E-Mail Fehler: {str(e)}"
    
    def send_booking_confirmation(self, user_email, user_name, slot_date, slot_time):
        """Buchungsbestätigung senden"""
        subject = f"✅ Schicht gebucht - {slot_date}"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #DC143C;">🌊 Wasserwacht Dienstplan</h2>
            <h3>Buchungsbestätigung</h3>
            <p>Hallo <strong>{user_name}</strong>,</p>
            <p>deine Schicht wurde erfolgreich gebucht:</p>
            <div style="background: #F5F7FA; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>📅 Datum:</strong> {slot_date}</p>
                <p><strong>⏰ Uhrzeit:</strong> {slot_time}</p>
            </div>
            <p>Du erhältst automatische Erinnerungen:</p>
            <ul>
                <li>24 Stunden vor Schichtbeginn</li>
                <li>1 Stunde vor Schichtbeginn</li>
            </ul>
            <p>Vielen Dank für deinen Einsatz!</p>
            <hr>
            <p style="font-size: 12px; color: #666;">
                Wasserwacht Dienstplan+ | {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}
            </p>
        </body>
        </html>
        """
        return self.send_email(user_email, subject, body)
    
    def send_cancellation(self, user_email, user_name, slot_date, slot_time):
        """Stornierungsbestätigung senden"""
        subject = f"❌ Schicht storniert - {slot_date}"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #DC143C;">🌊 Wasserwacht Dienstplan</h2>
            <h3>Stornierung</h3>
            <p>Hallo <strong>{user_name}</strong>,</p>
            <p>deine Schicht wurde storniert:</p>
            <div style="background: #FFE5E5; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>📅 Datum:</strong> {slot_date}</p>
                <p><strong>⏰ Uhrzeit:</strong> {slot_time}</p>
            </div>
            <p>Du kannst jederzeit eine neue Schicht buchen.</p>
            <hr>
            <p style="font-size: 12px; color: #666;">
                Wasserwacht Dienstplan+ | {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}
            </p>
        </body>
        </html>
        """
        return self.send_email(user_email, subject, body)
    
    def send_reminder(self, user_email, user_name, slot_date, slot_time, hours_before):
        """Erinnerung senden"""
        subject = f"⏰ Erinnerung: Schicht in {hours_before}h"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #DC143C;">🌊 Wasserwacht Dienstplan</h2>
            <h3>Schicht-Erinnerung</h3>
            <p>Hallo <strong>{user_name}</strong>,</p>
            <p>Deine Schicht beginnt in <strong>{hours_before} Stunden</strong>:</p>
            <div style="background: #FFF4E5; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>📅 Datum:</strong> {slot_date}</p>
                <p><strong>⏰ Uhrzeit:</strong> {slot_time}</p>
            </div>
            <p>Wir freuen uns auf dich!</p>
            <hr>
            <p style="font-size: 12px; color: #666;">
                Wasserwacht Dienstplan+ | {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}
            </p>
        </body>
        </html>
        """
        return self.send_email(user_email, subject, body)
    
    def send_test_email(self, to):
        """Test-E-Mail senden"""
        subject = "🧪 Test-E-Mail - Wasserwacht Dienstplan+"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #17BF63;">✅ E-Mail funktioniert!</h2>
            <p>Diese Test-E-Mail wurde erfolgreich versendet.</p>
            <div style="background: #F5F7FA; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p><strong>Server:</strong> {self.server}:{self.port}</p>
                <p><strong>Absender:</strong> {self.user}</p>
                <p><strong>Zeitpunkt:</strong> {datetime.now(TZ).strftime('%d.%m.%Y %H:%M:%S')}</p>
            </div>
            <p style="color: #17BF63; font-weight: bold;">✅ E-Mail-System ist korrekt konfiguriert!</p>
        </body>
        </html>
        """
        return self.send_email(to, subject, body)


# ===== SMS KLASSE MIT DETAILLIERTEM LOGGING =====
class SMSNotifier:
    """Verbesserte SMS-Klasse mit detailliertem Error-Handling"""
    
    def __init__(self):
        if hasattr(st, 'secrets'):
            self.account_sid = st.secrets.get("TWILIO_ACCOUNT_SID", "")
            self.auth_token = st.secrets.get("TWILIO_AUTH_TOKEN", "")
            self.from_number = st.secrets.get("TWILIO_FROM_NUMBER", "")
        else:
            raise ValueError("❌ Streamlit Secrets nicht gefunden!")
        
        # Validierung
        if not self.account_sid or not self.auth_token or not self.from_number:
            raise ValueError("❌ Twilio Credentials fehlen in Secrets!")
        
        # Twilio Client initialisieren
        try:
            self.client = Client(self.account_sid, self.auth_token)
        except Exception as e:
            raise ValueError(f"❌ Twilio Client Init Fehler: {str(e)}")
    
    def send_sms(self, to_number, message):
        """
        SMS senden mit detailliertem Error-Handling
        
        Args:
            to_number: Empfänger-Nummer (Format: +49...)
            message: SMS-Text
            
        Returns:
            (success: bool, message: str)
        """
        try:
            # Nummer validieren
            if not to_number.startswith('+'):
                return False, f"❌ Telefonnummer muss mit + beginnen! Aktuell: {to_number}"
            
            # SMS senden
            msg = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number
            )
            
            success_msg = f"✅ SMS gesendet an {to_number} (SID: {msg.sid})"
            print(success_msg)
            return True, success_msg
            
        except TwilioRestException as e:
            # Spezifische Twilio-Fehler
            error_code = e.code
            error_msg = e.msg
            
            # Bekannte Fehlercodes behandeln
            if error_code == 21211:
                return False, f"❌ Ungültige Telefonnummer: {to_number}"
            elif error_code == 21608:
                return False, f"❌ Nummer nicht verifiziert (Trial-Account): {to_number}"
            elif error_code == 21610:
                return False, f"❌ Nummer ist auf Blacklist: {to_number}"
            elif error_code == 21614:
                return False, "❌ 'To' Nummer ist nicht gültig"
            elif error_code == 21408:
                return False, "❌ Empfänger hat SMS-Empfang deaktiviert"
            else:
                return False, f"❌ Twilio Fehler {error_code}: {error_msg}"
                
        except Exception as e:
            error_msg = f"❌ Unerwarteter SMS Fehler: {str(e)}"
            print(error_msg)
            return False, error_msg
    
    def send_booking_confirmation(self, phone, name, slot_date, slot_time):
        """SMS Buchungsbestätigung"""
        message = f"""🌊 Wasserwacht Dienstplan

Hallo {name}!

✅ Schicht gebucht:
📅 {slot_date}
⏰ {slot_time}

Du erhältst Erinnerungen 24h & 1h vorher.

Danke für deinen Einsatz!"""
        return self.send_sms(phone, message)
    
    def send_cancellation(self, phone, name, slot_date, slot_time):
        """SMS Stornierung"""
        message = f"""🌊 Wasserwacht Dienstplan

Hallo {name}!

❌ Schicht storniert:
📅 {slot_date}
⏰ {slot_time}

Du kannst jederzeit neu buchen."""
        return self.send_sms(phone, message)
    
    def send_reminder(self, phone, name, slot_date, slot_time, hours_before):
        """SMS Erinnerung"""
        message = f"""🌊 Wasserwacht Dienstplan

Hallo {name}!

⏰ Deine Schicht in {hours_before}h:
📅 {slot_date}
⏰ {slot_time}

Wir freuen uns auf dich!"""
        return self.send_sms(phone, message)
    
    def send_test_sms(self, to_number):
        """Test-SMS senden"""
        message = f"""🧪 Test-SMS

✅ SMS-System funktioniert!

Wasserwacht Dienstplan+
{datetime.now(TZ).strftime('%d.%m.%Y %H:%M')}"""
        return self.send_sms(to_number, message)


# ===== HELPER FUNKTION: INITIALISIERUNG =====
def init_notifiers():
    """Notifier initialisieren und zurückgeben"""
    try:
        email_notifier = EmailNotifier()
        sms_notifier = SMSNotifier()
        return email_notifier, sms_notifier, True, "✅ Notification-System bereit"
    except ValueError as e:
        return None, None, False, str(e)
    except Exception as e:
        return None, None, False, f"❌ Init Fehler: {str(e)}"
