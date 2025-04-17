# meetings/consumers.py
import json
import logging
import asyncio
from uuid import uuid4
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.exceptions import ObjectDoesNotExist

from meetings.models import Meeting, MeetingParticipant, Transcript, Translation
from translate_api.services import TranslationService, AISuggestionService, SpeechProcessingService

logger = logging.getLogger(__name__)

class MeetingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.meeting_id = self.scope['url_route']['kwargs']['meeting_id']
        self.meeting_group_name = f'meeting_{self.meeting_id}'
        self.user = self.scope['user']
        self.participant_id = None
        
        # Verificare meeting și adăugare participant
        meeting_exists = await self.check_meeting_exists()
        if not meeting_exists:
            await self.close()
            return
        
        # Adăugare la grup pentru transmisia mesajelor
        await self.channel_layer.group_add(
            self.meeting_group_name,
            self.channel_name
        )
        
        # Adăugare participant și autentificare
        self.participant_id = await self.add_participant()
        if not self.participant_id:
            await self.close()
            return
        
        await self.accept()
        
        # Notificare alți participanți despre conectare
        await self.channel_layer.group_send(
            self.meeting_group_name,
            {
                'type': 'participant_joined',
                'participant_id': self.participant_id,
                'name': await self.get_participant_name()
            }
        )
    
    async def disconnect(self, close_code):
        if self.participant_id:
            # Marcare participant ca deconectat
            await self.mark_participant_left()
            
            # Notificare alți participanți despre deconectare
            await self.channel_layer.group_send(
                self.meeting_group_name,
                {
                    'type': 'participant_left',
                    'participant_id': self.participant_id,
                    'name': await self.get_participant_name()
                }
            )
        
        # Eliminare din grup
        await self.channel_layer.group_discard(
            self.meeting_group_name,
            self.channel_name
        )
    
    async def receive(self, text_data):
        """Primire date de la client."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'speech':
                # Procesare audio speech
                await self.process_speech(data)
            elif message_type == 'chat_message':
                # Procesare mesaj text
                await self.process_chat_message(data)
            elif message_type == 'request_suggestions':
                # Generare sugestii AI
                await self.generate_suggestions(data)
            elif message_type == 'request_meeting_info':
                # Trimitere informații despre meeting
                await self.send_meeting_info()
            elif message_type == 'request_participants':
                # Trimitere lista participanți
                await self.send_participants_list()
        except json.JSONDecodeError:
            logger.error(f"Eroare decodare JSON: {text_data}")
        except Exception as e:
            logger.error(f"Eroare la primire mesaj: {str(e)}")
    
    async def process_speech(self, data):
        """Procesează un fragment audio, extrage text și traduce."""
        audio_data = data.get('audio_data')
        source_language = data.get('language', 'en-US')
        
        if not audio_data:
            return
        
        # Procesare audio în text
        text = SpeechProcessingService.process_speech_chunk(audio_data, source_language)
        
        if not text:
            return
        
        # Salvare transcript
        transcript_id = await self.save_transcript(text, source_language)
        
        # Obținere meeting și limbi țintă
        meeting_info = await self.get_meeting_info()
        participant_languages = await self.get_participant_languages()
        
        # Traducere pentru fiecare limbă țintă
        translations = {}
        for lang in participant_languages:
            if lang != source_language.split('-')[0]:  # Nu traducem în aceeași limbă
                translated_text = TranslationService.translate_text(
                    text, 
                    source_lang=source_language.split('-')[0],
                    target_lang=lang
                )
                translations[lang] = translated_text
                
                # Salvare traducere în baza de date
                if transcript_id:
                    await self.save_translation(transcript_id, translated_text, lang)
        
        # Trimitere mesaj către toți participanții
        await self.channel_layer.group_send(
            self.meeting_group_name,
            {
                'type': 'speech_message',
                'participant_id': self.participant_id,
                'name': await self.get_participant_name(),
                'original_text': text,
                'original_language': source_language,
                'translations': translations,
                'timestamp': data.get('timestamp')
            }
        )
    
    async def process_chat_message(self, data):
        """Procesează un mesaj text din chat și îl traduce."""
        text = data.get('message')
        source_language = data.get('language', 'en')
        
        if not text:
            return
        
        # Obținere limbi țintă
        participant_languages = await self.get_participant_languages()
        
        # Traducere pentru fiecare limbă țintă
        translations = {}
        for lang in participant_languages:
            if lang != source_language:  # Nu traducem în aceeași limbă
                translated_text = TranslationService.translate_text(
                    text, 
                    source_lang=source_language,
                    target_lang=lang
                )
                translations[lang] = translated_text
        
        # Trimitere mesaj către toți participanții
        await self.channel_layer.group_send(
            self.meeting_group_name,
            {
                'type': 'chat_message',
                'participant_id': self.participant_id,
                'name': await self.get_participant_name(),
                'original_text': text,
                'original_language': source_language,
                'translations': translations,
                'timestamp': data.get('timestamp')
            }
        )
    
    async def generate_suggestions(self, data):
        """Generează sugestii AI pentru un participant."""
        context = data.get('context', '')
        language = data.get('language', 'ro')
        meeting_type = data.get('meeting_type', 'interview')
        user_role = data.get('user_role', 'interviewee')
        
        # Generare sugestii
        suggestions = AISuggestionService.generate_suggestions(
            context, language, meeting_type, user_role
        )
        
        # Trimitere sugestii doar către participantul care le-a cerut
        await self.send(text_data=json.dumps({
            'type': 'suggestions',
            'suggestions': suggestions
        }))
    
    async def speech_message(self, event):
        """Transmite un mesaj de tip speech către client."""
        # Trimite doar către client
        await self.send(text_data=json.dumps({
            'type': 'speech',
            'participant_id': event['participant_id'],
            'name': event['name'],
            'original_text': event['original_text'],
            'original_language': event['original_language'],
            'translations': event['translations'],
            'timestamp': event['timestamp']
        }))
    
    async def chat_message(self, event):
        """Transmite un mesaj de chat către client."""
        # Trimite doar către client
        await self.send(text_data=json.dumps({
            'type': 'chat',
            'participant_id': event['participant_id'],
            'name': event['name'],
            'original_text': event['original_text'],
            'original_language': event['original_language'],
            'translations': event['translations'],
            'timestamp': event['timestamp']
        }))
    
    async def participant_joined(self, event):
        """Notifică clienții că un participant s-a alăturat."""
        await self.send(text_data=json.dumps({
            'type': 'participant_joined',
            'participant_id': event['participant_id'],
            'name': event['name']
        }))
    
    async def participant_left(self, event):
        """Notifică clienții că un participant a plecat."""
        await self.send(text_data=json.dumps({
            'type': 'participant_left',
            'participant_id': event['participant_id'],
            'name': event['name']
        }))
    
    async def send_meeting_info(self):
        """Trimite informații despre meeting către client."""
        meeting_info = await self.get_meeting_info()
        
        await self.send(text_data=json.dumps({
            'type': 'meeting_info',
            'meeting': meeting_info
        }))
    
    async def send_participants_list(self):
        """Trimite lista de participanți către client."""
        participants = await self.get_participants()
        
        await self.send(text_data=json.dumps({
            'type': 'participants_list',
            'participants': participants
        }))
    
    # Metode auxiliare pentru interacțiunea cu baza de date
    
    @database_sync_to_async
    def check_meeting_exists(self):
        """Verifică dacă meeting-ul există."""
        try:
            meeting = Meeting.objects.get(id=self.meeting_id)
            return True
        except Meeting.DoesNotExist:
            return False
    
    @database_sync_to_async
    def add_participant(self):
        """Adaugă utilizatorul curent ca participant la meeting."""
        try:
            meeting = Meeting.objects.get(id=self.meeting_id)
            
            # Verificăm dacă utilizatorul este deja participant
            if self.user.is_authenticated:
                participant, created = MeetingParticipant.objects.get_or_create(
                    meeting=meeting,
                    user=self.user,
                    defaults={
                        'name': f"{self.user.first_name} {self.user.last_name}".strip() or self.user.username,
                        'email': self.user.email,
                        'preferred_language': self.user.preferred_language
                    }
                )
            else:
                # Dacă nu e autentificat, folosim un ID temporar
                participant = MeetingParticipant.objects.create(
                    meeting=meeting,
                    name=f"Guest-{uuid4().hex[:6]}",
                    preferred_language='en'  # Limbă implicită
                )
            
            return participant.id
        except Exception as e:
            logger.error(f"Eroare la adăugare participant: {str(e)}")
            return None
    
    @database_sync_to_async
    def mark_participant_left(self):
        """Marchează participantul ca plecat din meeting."""
        from django.utils import timezone
        
        try:
            participant = MeetingParticipant.objects.get(id=self.participant_id)
            participant.left_at = timezone.now()
            participant.save()
        except MeetingParticipant.DoesNotExist:
            pass
    
    @database_sync_to_async
    def get_participant_name(self):
        """Obține numele participantului curent."""
        try:
            participant = MeetingParticipant.objects.get(id=self.participant_id)
            return participant.name
        except MeetingParticipant.DoesNotExist:
            return "Unknown"
    
    @database_sync_to_async
    def get_meeting_info(self):
        """Obține informații despre meeting."""
        try:
            meeting = Meeting.objects.get(id=self.meeting_id)
            return {
                'id': meeting.id,
                'title': meeting.title,
                'status': meeting.status,
                'source_language': meeting.source_language,
                'target_language': meeting.target_language
            }
        except Meeting.DoesNotExist:
            return {}
    
    @database_sync_to_async
    def get_participant_languages(self):
        """Obține limbile preferate ale tuturor participanților."""
        try:
            participants = MeetingParticipant.objects.filter(meeting_id=self.meeting_id)
            languages = set()
            
            for participant in participants:
                languages.add(participant.preferred_language)
            
            return list(languages)
        except Exception:
            return ['en']  # Implicit English
    
    @database_sync_to_async
    def get_participants(self):
        """Obține lista de participanți la meeting."""
        try:
            participants = MeetingParticipant.objects.filter(meeting_id=self.meeting_id)
            return [
                {
                    'id': p.id,
                    'name': p.name,
                    'preferred_language': p.preferred_language
                }
                for p in participants
            ]
        except Exception:
            return []
    
    @database_sync_to_async
    def save_transcript(self, text, source_language):
        """Salvează o transcriere în baza de date."""
        try:
            transcript = Transcript.objects.create(
                meeting_id=self.meeting_id,
                participant_id=self.participant_id,
                original_text=text,
                source_language=source_language.split('-')[0]
            )
            return transcript.id
        except Exception as e:
            logger.error(f"Eroare la salvare transcript: {str(e)}")
            return None
    
    @database_sync_to_async
    def save_translation(self, transcript_id, translated_text, target_language):
        """Salvează o traducere în baza de date."""
        try:
            Translation.objects.create(
                transcript_id=transcript_id,
                translated_text=translated_text,
                target_language=target_language
            )
            return True
        except Exception as e:
            logger.error(f"Eroare la salvare traducere: {str(e)}")
            return False