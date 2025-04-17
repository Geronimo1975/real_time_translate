import json
import logging
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union

from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from accounts.models import User
from .models import Meeting, MeetingParticipant, Transcript, Translation

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manager for handling meeting/interview sessions.
    This class provides functionality for creating, joining, and managing sessions.
    """
    
    def __init__(self):
        self.active_sessions = {}  # cache of active sessions
        self.session_metrics = {}  # metrics for each session
        self.channel_layer = get_channel_layer()
    
    @transaction.atomic
    def create_session(self, title: str, owner_id: int, settings: Dict = None) -> Dict:
        """
        Create a new meeting/interview session.
        
        Args:
            title: The title of the meeting
            owner_id: User ID of the meeting creator/owner
            settings: Dictionary of meeting settings (source_language, target_language, etc.)
            
        Returns:
            Dictionary containing session information
            
        Raises:
            Exception: If user limit is reached or other validation errors
        """
        try:
            # Get the owner user
            owner = User.objects.get(id=owner_id)
            
            # Default settings if none provided
            if settings is None:
                settings = {}
            
            # Default session settings
            default_settings = {
                'source_language': 'en',
                'target_language': 'ro',
                'enable_recording': True,
                'enable_suggestions': True,
                'meeting_type': 'interview',  # or 'meeting'
                'max_participants': 10,
                'duration_minutes': 60
            }
            
            # Merge with provided settings
            for key, value in default_settings.items():
                if key not in settings:
                    settings[key] = value
            
            # Verify user limits based on their plan
            self._verify_user_limits(owner, settings)
            
            # Generate unique meeting URL
            meeting_url = f"{uuid.uuid4().hex[:8]}"
            while Meeting.objects.filter(meeting_url=meeting_url).exists():
                meeting_url = f"{uuid.uuid4().hex[:8]}"
            
            # Create meeting in database
            meeting = Meeting.objects.create(
                title=title,
                created_by=owner,
                status='scheduled',
                source_language=settings['source_language'],
                target_language=settings['target_language'],
                meeting_url=meeting_url,
                start_time=timezone.now() + timedelta(minutes=5)  # Default start time in 5 minutes
            )
            
            # Add owner as participant
            MeetingParticipant.objects.create(
                meeting=meeting,
                user=owner,
                email=owner.email,
                name=f"{owner.first_name} {owner.last_name}".strip() or owner.username,
                preferred_language=settings['source_language']
            )
            
            # Store in active sessions cache
            session_id = str(meeting.id)
            self.active_sessions[session_id] = {
                'id': session_id,
                'meeting': meeting,
                'owner_id': owner_id,
                'created_at': timezone.now(),
                'status': 'created',
                'settings': settings,
                'participants': [
                    {
                        'id': owner.id,
                        'name': f"{owner.first_name} {owner.last_name}".strip() or owner.username,
                        'role': 'owner'
                    }
                ]
            }
            
            # Initialize session metrics
            self.session_metrics[session_id] = {
                'total_audio_seconds': 0,
                'total_chars_translated': 0,
                'active_participants': 1,
                'languages_used': set([settings['source_language']]),
                'start_time': None,
                'end_time': None
            }
            
            return {
                'id': session_id,
                'title': meeting.title,
                'meeting_url': meeting.meeting_url,
                'status': meeting.status,
                'settings': settings
            }
            
        except ObjectDoesNotExist:
            logger.error(f"User with ID {owner_id} not found")
            raise Exception("Invalid user ID")
        except Exception as e:
            logger.error(f"Error creating session: {str(e)}")
            raise
    
    def get_session(self, session_id: str) -> Dict:
        """
        Get information about a session.
        
        Args:
            session_id: ID of the session to retrieve
            
        Returns:
            Dictionary containing session information
            
        Raises:
            Exception: If session doesn't exist
        """
        # Try to get from active sessions cache
        if session_id in self.active_sessions:
            return self.active_sessions[session_id]
        
        # If not in cache, try to get from database
        try:
            meeting = Meeting.objects.get(id=session_id)
            
            # Load session into cache
            participants = MeetingParticipant.objects.filter(meeting=meeting)
            participant_list = []
            
            for p in participants:
                participant_dict = {
                    'id': p.user.id if p.user else None,
                    'name': p.name,
                    'email': p.email,
                    'preferred_language': p.preferred_language,
                    'role': 'owner' if p.user and p.user.id == meeting.created_by.id else 'participant'
                }
                participant_list.append(participant_dict)
            
            # Reconstruct settings
            settings = {
                'source_language': meeting.source_language,
                'target_language': meeting.target_language,
                'enable_recording': True,  # Default
                'enable_suggestions': True,  # Default
                'meeting_type': 'interview',  # Default
                'max_participants': 10,  # Default
            }
            
            # Store in active sessions cache
            self.active_sessions[session_id] = {
                'id': session_id,
                'meeting': meeting,
                'owner_id': meeting.created_by.id,
                'created_at': meeting.created_at,
                'status': meeting.status,
                'settings': settings,
                'participants': participant_list
            }
            
            # Initialize metrics if needed
            if session_id not in self.session_metrics:
                self.session_metrics[session_id] = {
                    'total_audio_seconds': 0,
                    'total_chars_translated': 0,
                    'active_participants': len(participant_list),
                    'languages_used': set([p['preferred_language'] for p in participant_list]),
                    'start_time': meeting.start_time,
                    'end_time': meeting.end_time
                }
            
            return self.active_sessions[session_id]
            
        except ObjectDoesNotExist:
            logger.error(f"Meeting with ID {session_id} not found")
            raise Exception("Invalid session ID")
        except Exception as e:
            logger.error(f"Error retrieving session: {str(e)}")
            raise
    
    @transaction.atomic
    def join_session(self, session_id: str, user_id: Optional[int] = None, 
                    guest_info: Optional[Dict] = None) -> Dict:
        """
        Join an existing session as an authenticated user or guest.
        
        Args:
            session_id: ID of the session to join
            user_id: User ID for authenticated users (optional)
            guest_info: Dictionary with guest information for unauthenticated users (optional)
            
        Returns:
            Dictionary with participant information
            
        Raises:
            Exception: If session doesn't exist or other validation errors
        """
        try:
            # Get session information
            session = self.get_session(session_id)
            meeting = session['meeting']
            
            # Check if session is joinable
            if meeting.status not in ['scheduled', 'live']:
                raise Exception(f"Cannot join meeting with status: {meeting.status}")
            
            participant_info = {}
            
            # Handle authenticated user
            if user_id is not None:
                user = User.objects.get(id=user_id)
                
                # Check if already a participant
                existing = MeetingParticipant.objects.filter(meeting=meeting, user=user).first()
                if existing:
                    # Update join time if rejoining
                    existing.joined_at = timezone.now()
                    existing.left_at = None
                    existing.save()
                    
                    participant_info = {
                        'id': existing.id,
                        'user_id': user.id,
                        'name': existing.name,
                        'email': existing.email,
                        'preferred_language': existing.preferred_language,
                        'role': 'owner' if user.id == meeting.created_by.id else 'participant'
                    }
                else:
                    # Create new participant
                    participant = MeetingParticipant.objects.create(
                        meeting=meeting,
                        user=user,
                        email=user.email,
                        name=f"{user.first_name} {user.last_name}".strip() or user.username,
                        preferred_language=user.preferred_language or meeting.target_language,
                        joined_at=timezone.now()
                    )
                    
                    participant_info = {
                        'id': participant.id,
                        'user_id': user.id,
                        'name': participant.name,
                        'email': participant.email,
                        'preferred_language': participant.preferred_language,
                        'role': 'owner' if user.id == meeting.created_by.id else 'participant'
                    }
            
            # Handle guest user
            elif guest_info is not None:
                # Validate guest info
                if 'name' not in guest_info:
                    raise Exception("Guest name is required")
                
                # Create guest participant
                participant = MeetingParticipant.objects.create(
                    meeting=meeting,
                    user=None,
                    email=guest_info.get('email'),
                    name=guest_info['name'],
                    preferred_language=guest_info.get('preferred_language', meeting.target_language),
                    joined_at=timezone.now()
                )
                
                participant_info = {
                    'id': participant.id,
                    'user_id': None,
                    'name': participant.name,
                    'email': participant.email,
                    'preferred_language': participant.preferred_language,
                    'role': 'guest'
                }
            
            else:
                raise Exception("Either user_id or guest_info must be provided")
            
            # Update session status if it's the first participant
            if meeting.status == 'scheduled':
                meeting.status = 'live'
                meeting.start_time = timezone.now()
                meeting.save()
                
                # Update metrics
                self.session_metrics[session_id]['start_time'] = meeting.start_time
                self.session_metrics[session_id]['active_participants'] += 1
                self.session_metrics[session_id]['languages_used'].add(participant_info['preferred_language'])
            
            # Update session cache
            self._update_session_participants(session_id)
            
            # Notify other participants
            self._notify_participant_joined(session_id, participant_info)
            
            return participant_info
            
        except ObjectDoesNotExist:
            logger.error(f"User or meeting not found: session_id={session_id}, user_id={user_id}")
            raise Exception("Invalid session or user")
        except Exception as e:
            logger.error(f"Error joining session: {str(e)}")
            raise
    
    @transaction.atomic
    def leave_session(self, session_id: str, participant_id: int) -> bool:
        """
        Leave a session.
        
        Args:
            session_id: ID of the session
            participant_id: ID of the participant leaving
            
        Returns:
            True if successful
            
        Raises:
            Exception: If session or participant doesn't exist
        """
        try:
            # Get session information
            session = self.get_session(session_id)
            meeting = session['meeting']
            
            # Get participant
            participant = MeetingParticipant.objects.get(id=participant_id, meeting=meeting)
            
            # Update leave time
            participant.left_at = timezone.now()
            participant.save()
            
            # Update metrics
            self.session_metrics[session_id]['active_participants'] -= 1
            
            # If all participants have left, end the meeting
            active_participants = MeetingParticipant.objects.filter(
                meeting=meeting, 
                left_at__isnull=True
            ).count()
            
            if active_participants == 0 and meeting.status == 'live':
                meeting.status = 'completed'
                meeting.end_time = timezone.now()
                meeting.save()
                
                # Update metrics
                self.session_metrics[session_id]['end_time'] = meeting.end_time
            
            # Update session cache
            self._update_session_participants(session_id)
            
            # Notify other participants
            self._notify_participant_left(session_id, participant_id, participant.name)
            
            return True
            
        except ObjectDoesNotExist:
            logger.error(f"Participant or meeting not found: session_id={session_id}, participant_id={participant_id}")
            raise Exception("Invalid session or participant")
        except Exception as e:
            logger.error(f"Error leaving session: {str(e)}")
            raise
    
    @transaction.atomic
    def end_session(self, session_id: str, user_id: int) -> bool:
        """
        End a session (only by owner or authorized user).
        
        Args:
            session_id: ID of the session to end
            user_id: ID of the user ending the session
            
        Returns:
            True if successful
            
        Raises:
            Exception: If session doesn't exist or user is not authorized
        """
        try:
            # Get session information
            session = self.get_session(session_id)
            meeting = session['meeting']
            
            # Verify user is owner or admin
            if user_id != meeting.created_by.id and not User.objects.get(id=user_id).is_staff:
                raise Exception("Not authorized to end this session")
            
            # End meeting
            meeting.status = 'completed'
            meeting.end_time = timezone.now()
            meeting.save()
            
            # Update metrics
            self.session_metrics[session_id]['end_time'] = meeting.end_time
            
            # Mark all participants as left
            MeetingParticipant.objects.filter(
                meeting=meeting, 
                left_at__isnull=True
            ).update(left_at=timezone.now())
            
            # Update session cache
            self._update_session_participants(session_id)
            
            # Notify participants
            self._notify_session_ended(session_id)
            
            return True
            
        except ObjectDoesNotExist:
            logger.error(f"Meeting or user not found: session_id={session_id}, user_id={user_id}")
            raise Exception("Invalid session or user")
        except Exception as e:
            logger.error(f"Error ending session: {str(e)}")
            raise
    
    def add_transcript(self, session_id: str, participant_id: int, 
                      text: str, source_language: str) -> int:
        """
        Add a speech transcript to the session.
        
        Args:
            session_id: ID of the session
            participant_id: ID of the participant who spoke
            text: Transcribed text
            source_language: Language of the transcript
            
        Returns:
            ID of the created transcript
            
        Raises:
            Exception: If session or participant doesn't exist
        """
        try:
            # Get session information
            session = self.get_session(session_id)
            meeting = session['meeting']
            
            # Get participant
            participant = MeetingParticipant.objects.get(id=participant_id, meeting=meeting)
            
            # Create transcript
            transcript = Transcript.objects.create(
                meeting=meeting,
                participant=participant,
                original_text=text,
                source_language=source_language
            )
            
            # Update metrics
            self.session_metrics[session_id]['total_chars_translated'] += len(text)
            
            return transcript.id
            
        except ObjectDoesNotExist:
            logger.error(f"Participant or meeting not found: session_id={session_id}, participant_id={participant_id}")
            raise Exception("Invalid session or participant")
        except Exception as e:
            logger.error(f"Error adding transcript: {str(e)}")
            raise
    
    def add_translation(self, transcript_id: int, translated_text: str, 
                       target_language: str) -> int:
        """
        Add a translation for a transcript.
        
        Args:
            transcript_id: ID of the transcript to translate
            translated_text: Translated text
            target_language: Target language of the translation
            
        Returns:
            ID of the created translation
            
        Raises:
            Exception: If transcript doesn't exist
        """
        try:
            # Get transcript
            transcript = Transcript.objects.get(id=transcript_id)
            
            # Create translation
            translation = Translation.objects.create(
                transcript=transcript,
                translated_text=translated_text,
                target_language=target_language
            )
            
            return translation.id
            
        except ObjectDoesNotExist:
            logger.error(f"Transcript not found: transcript_id={transcript_id}")
            raise Exception("Invalid transcript")
        except Exception as e:
            logger.error(f"Error adding translation: {str(e)}")
            raise
    
    def get_session_transcripts(self, session_id: str, language: Optional[str] = None) -> List[Dict]:
        """
        Get all transcripts for a session, optionally in a specific language.
        
        Args:
            session_id: ID of the session
            language: Language code to return transcripts in (optional)
            
        Returns:
            List of transcript dictionaries
            
        Raises:
            Exception: If session doesn't exist
        """
        try:
            # Get session information
            session = self.get_session(session_id)
            meeting = session['meeting']
            
            # Get all transcripts
            transcripts = Transcript.objects.filter(meeting=meeting).order_by('timestamp')
            
            result = []
            
            for transcript in transcripts:
                item = {
                    'id': transcript.id,
                    'participant_id': transcript.participant.id,
                    'participant_name': transcript.participant.name,
                    'original_text': transcript.original_text,
                    'original_language': transcript.source_language,
                    'timestamp': transcript.timestamp.isoformat(),
                    'translations': {}
                }
                
                # Get translations
                translations = Translation.objects.filter(transcript=transcript)
                
                for translation in translations:
                    item['translations'][translation.target_language] = {
                        'id': translation.id,
                        'text': translation.translated_text,
                        'timestamp': translation.timestamp.isoformat()
                    }
                
                # If specific language is requested
                if language:
                    # If requested language is the original language
                    if language == transcript.source_language:
                        item['text'] = transcript.original_text
                    # If requested language has a translation
                    elif language in item['translations']:
                        item['text'] = item['translations'][language]['text']
                    # Otherwise use original text
                    else:
                        item['text'] = transcript.original_text
                
                result.append(item)
            
            return result
            
        except ObjectDoesNotExist:
            logger.error(f"Meeting not found: session_id={session_id}")
            raise Exception("Invalid session")
        except Exception as e:
            logger.error(f"Error getting session transcripts: {str(e)}")
            raise
    
    def get_session_metrics(self, session_id: str) -> Dict:
        """
        Get metrics for a session.
        
        Args:
            session_id: ID of the session
            
        Returns:
            Dictionary with session metrics
            
        Raises:
            Exception: If session doesn't exist
        """
        try:
            # Get session information
            session = self.get_session(session_id)
            meeting = session['meeting']
            
            # Get metrics
            metrics = self.session_metrics.get(session_id, {})
            
            # Compute duration if available
            duration_seconds = None
            if metrics.get('start_time') and metrics.get('end_time'):
                duration_seconds = (metrics['end_time'] - metrics['start_time']).total_seconds()
            elif metrics.get('start_time'):
                duration_seconds = (timezone.now() - metrics['start_time']).total_seconds()
            
            # Count total participants
            total_participants = MeetingParticipant.objects.filter(meeting=meeting).count()
            
            # Get transcript count
            transcript_count = Transcript.objects.filter(meeting=meeting).count()
            
            # Additional metrics from database
            result = {
                'session_id': session_id,
                'title': meeting.title,
                'status': meeting.status,
                'start_time': metrics.get('start_time'),
                'end_time': metrics.get('end_time'),
                'duration_seconds': duration_seconds,
                'total_participants': total_participants,
                'active_participants': metrics.get('active_participants', 0),
                'transcript_count': transcript_count,
                'total_chars_translated': metrics.get('total_chars_translated', 0),
                'languages_used': list(metrics.get('languages_used', set())),
                'created_by': meeting.created_by.username
            }
            
            return result
            
        except ObjectDoesNotExist:
            logger.error(f"Meeting not found: session_id={session_id}")
            raise Exception("Invalid session")
        except Exception as e:
            logger.error(f"Error getting session metrics: {str(e)}")
            raise
    
    def _update_session_participants(self, session_id: str) -> None:
        """
        Update the participant information in session cache.
        
        Args:
            session_id: ID of the session to update
        """
        if session_id not in self.active_sessions:
            return
        
        try:
            meeting = Meeting.objects.get(id=session_id)
            participants = MeetingParticipant.objects.filter(meeting=meeting)
            
            participant_list = []
            for p in participants:
                participant_dict = {
                    'id': p.id,
                    'user_id': p.user.id if p.user else None,
                    'name': p.name,
                    'email': p.email,
                    'preferred_language': p.preferred_language,
                    'joined_at': p.joined_at.isoformat() if p.joined_at else None,
                    'left_at': p.left_at.isoformat() if p.left_at else None,
                    'role': 'owner' if p.user and p.user.id == meeting.created_by.id else 'participant'
                }
                participant_list.append(participant_dict)
            
            self.active_sessions[session_id]['participants'] = participant_list
            self.active_sessions[session_id]['status'] = meeting.status
            
        except Exception as e:
            logger.error(f"Error updating session participants: {str(e)}")
    
    def _verify_user_limits(self, user: User, settings: Dict) -> None:
        """
        Verify that user is within their plan limits.
        
        Args:
            user: User to check
            settings: Session settings
            
        Raises:
            Exception: If user is over limits
        """
        # Check if user has premium features
        if not user.is_premium:
            if settings.get('max_participants', 10) > 3:
                raise Exception("Free plan limited to 3 participants")
            
            # Check available minutes
            if user.available_minutes <= 0:
                raise Exception("No available minutes remaining")
        
        # Check concurrent sessions for all users
        active_sessions = Meeting.objects.filter(
            created_by=user,
            status__in=['scheduled', 'live']
        ).count()
        
        max_concurrent = 1  # Free plan
        if user.is_premium:
            max_concurrent = 5  # Premium plan
        
        if active_sessions >= max_concurrent:
            raise Exception(f"Maximum of {max_concurrent} concurrent sessions allowed")
    
    def _notify_participant_joined(self, session_id: str, participant_info: Dict) -> None:
        """
        Notify all participants that someone joined.
        
        Args:
            session_id: ID of the session
            participant_info: Information about the joined participant
        """
        try:
            message = {
                'type': 'participant_joined',
                'participant_id': participant_info['id'],
                'name': participant_info['name'],
                'preferred_language': participant_info['preferred_language'],
                'role': participant_info['role'],
                'timestamp': timezone.now().isoformat()
            }
            
            async_to_sync(self.channel_layer.group_send)(
                f"meeting_{session_id}",
                message
            )
            
        except Exception as e:
            logger.error(f"Error notifying participant joined: {str(e)}")
    
    def _notify_participant_left(self, session_id: str, participant_id: int, name: str) -> None:
        """
        Notify all participants that someone left.
        
        Args:
            session_id: ID of the session
            participant_id: ID of the participant who left
            name: Name of the participant who left
        """
        try:
            message = {
                'type': 'participant_left',
                'participant_id': participant_id,
                'name': name,
                'timestamp': timezone.now().isoformat()
            }
            
            async_to_sync(self.channel_layer.group_send)(
                f"meeting_{session_id}",
                message
            )
            
        except Exception as e:
            logger.error(f"Error notifying participant left: {str(e)}")
    
    def _notify_session_ended(self, session_id: str) -> None:
        """
        Notify all participants that the session has ended.
        
        Args:
            session_id: ID of the session
        """
        try:
            message = {
                'type': 'session_ended',
                'session_id': session_id,
                'timestamp': timezone.now().isoformat()
            }
            
            async_to_sync(self.channel_layer.group_send)(
                f"meeting_{session_id}",
                message
            )
            
        except Exception as e:
            logger.error(f"Error notifying session ended: {str(e)}")


# Initialize a singleton instance
session_manager = SessionManager()


class AIAssistantService:
    """
    Service for generating AI suggestions and recommendations during meetings.
    
    This is a placeholder implementation. In a real-world scenario,
    you would integrate with OpenAI API or other LLM providers.
    """
    
    def __init__(self):
        # API key configuration
        self.openai_api_key = getattr(settings, 'OPENAI_API_KEY', os.environ.get('OPENAI_API_KEY', ''))
        
        # Metrics for monitoring
        self.metrics = {
            'suggestions_generated': 0,
            'errors': 0,
            'avg_response_time': [],
        }
    
    def generate_suggestions(self, context: List[Dict], user_role: str, 
                           language: str, meeting_type: str = 'interview',
                           num_suggestions: int = 3) -> List[str]:
        """
        Generate contextual suggestions based on meeting transcript.
        
        Args:
            context: List of recent transcript entries
            user_role: Role of the user (interviewer, interviewee, etc.)
            language: Language to generate suggestions in
            meeting_type: Type of meeting (interview, meeting, etc.)
            num_suggestions: Number of suggestions to generate
            
        Returns:
            List of suggestion strings
        """
        # In a real implementation, this would call OpenAI API or other LLM
        start_time = time.time()
        
        try:
            # Format context for prompt
            formatted_context = "\n".join([
                f"{item.get('participant_name', 'Unknown')}: {item.get('text', item.get('original_text', ''))}"
                for item in context[-5:]  # Last 5 messages
            ])
            
            # Select prompt based on meeting type and role
            prompt = self._get_prompt(meeting_type, user_role, language)
            
            # In a real implementation, call OpenAI API here
            # For now, return mock suggestions
            suggestions = self._mock_suggestions(user_role, meeting_type, language, formatted_context)
            
            execution_time = time.time() - start_time
            self.metrics['avg_response_time'].append(execution_time)
            self.metrics['suggestions_generated'] += 1
            
            return suggestions[:num_suggestions]
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Error generating suggestions: {str(e)}")
            
            # Return generic suggestions as fallback
            if language == 'ro':
                return ["Ne pare rău, nu am putut genera sugestii personalizate."]
            else:
                return ["Sorry, we couldn't generate personalized suggestions."]
    
    def _get_prompt(self, meeting_type: str, user_role: str, language: str) -> str:
        """
        Get the appropriate prompt based on meeting type and user role.
        
        Args:
            meeting_type: Type of meeting
            user_role: Role of the user
            language: Language for the prompt
            
        Returns:
            Prompt string
        """
        prompts = {
            'interview': {
                'interviewer': {
                    'en': "You are an experienced interviewer. Based on the conversation context, suggest follow-up questions:",
                    'ro': "Ești un intervievator experimentat. Pe baza contextului conversației, sugerează întrebări de urmărire:"
                },
                'interviewee': {
                    'en': "You are a job candidate. Based on the conversation context, suggest professional responses:",
                    'ro': "Ești un candidat pentru un job. Pe baza contextului conversației, sugerează răspunsuri profesionale:"
                }
            },
            'meeting': {
                'host': {
                    'en': "You are a meeting facilitator. Based on the conversation context, suggest talking points to move the discussion forward:",
                    'ro': "Ești un facilitator de întâlniri. Pe baza contextului conversației, sugerează puncte de discuție pentru a avansa conversația:"
                },
                'participant': {
                    'en': "You are a meeting participant. Based on the conversation context, suggest constructive contributions:",
                    'ro': "Ești un participant la o întâlnire. Pe baza contextului conversației, sugerează contribuții constructive:"
                }
            }
        }
        
        # Get the appropriate prompt or default to English interviewer
        meeting_prompts = prompts.get(meeting_type, prompts['interview'])
        role_prompts = meeting_prompts.get(user_role, meeting_prompts['interviewer'])
        return role_prompts.get(language, role_prompts['en'])
    
    def _mock_suggestions(self, user_role: str, meeting_type: str, 
                         language: str, context: str) -> List[str]:
        """
        Generate mock suggestions for demo purposes.
        
        Args:
            user_role: Role of the user
            meeting_type: Type of meeting
            language: Language for suggestions
            context: Conversation context
            
        Returns:
            List of suggestion strings
        """
        # Basic mock suggestions based on role and language
        if meeting_type == 'interview':
            if user_role == 'interviewer':
                if language == 'ro':
                    return [
                        "Puteți detalia mai mult despre experiența dvs. cu acest tip de proiecte?",
                        "Care au fost cele mai mari provocări pe care le-ați întâmpinat și cum le-ați depășit?",
                        "Cum vă vedeți contribuind la echipa noastră cu aceste competențe?"
                    ]
                else:
                    return [
                        "Can you elaborate more on your experience with these types of projects?",
                        "What were the biggest challenges you faced and how did you overcome them?",
                        "How do you see yourself contributing to our team with these skills?"
                    ]
            else:  # interviewee
                if language == 'ro':
                    return [
                        "În rolul meu anterior, am fost responsabil pentru implementarea unor soluții similare care au îmbunătățit eficiența cu 30%.",
                        "Am experiență extinsă în acest domeniu, lucrând cu tehnologii de ultimă generație pentru a rezolva probleme complexe.",
                        "Un exemplu concret ar fi proiectul X, unde am condus o echipă de 5 persoane pentru a livra soluția cu 2 săptămâni înainte de termen."
                    ]
                else:
                    return [
                        "In my previous role, I was responsible for implementing similar solutions that improved efficiency by 30%.",
                        "I have extensive experience in this field, working with cutting-edge technologies to solve complex problems.",
                        "A concrete example would be Project X, where I led a team of 5 people to deliver the solution 2 weeks ahead of schedule."
                    ]
        else:  # meeting
            if user_role == 'host':
                if language == 'ro':
                    return [
                        "Să trecem la următorul punct de pe agendă: implementarea noii funcționalități.",
                        "Putem să recapitulăm deciziile luate până acum și să stabilim următorii pași?",
                        "Aș dori să aud părerea fiecăruia despre propunerea discutată."
                    ]
                else:
                    return [
                        "Let's move to the next item on the agenda: implementing the new feature.",
                        "Can we recap the decisions made so far and establish next steps?",
                        "I'd like to hear everyone's opinion on the discussed proposal."
                    ]
            else:  # participant
                if language == 'ro':
                    return [
                        "Din perspectiva mea, cred că ar trebui să prioritizăm îmbunătățirea performanței înainte de a adăuga funcționalități noi.",
                        "Aș dori să adaug că acest aspect ar putea afecta și echipa de suport, așa că ar trebui să-i implicăm în discuție.",
                        "Sunt de acord cu ideea generală, dar propun să o implementăm în etape pentru a minimiza riscurile."
                    ]
                else:
                    return [
                        "From my perspective, I think we should prioritize performance improvements before adding new features.",
                        "I'd like to add that this aspect might also affect the support team, so we should involve them in the discussion.",
                        "I agree with the general idea, but I suggest implementing it in stages to minimize risks."
                    ]
    
    def get_metrics(self) -> Dict:
        """
        Get service metrics.
        
        Returns:
            Dictionary with service metrics
        """
        avg_time = 0
        if self.metrics['avg_response_time']:
            avg_time = sum(self.metrics['avg_response_time']) / len(self.metrics['avg_response_time'])
        
        return {
            'suggestions_generated': self.metrics['suggestions_generated'],
            'errors': self.metrics['errors'],
            'error_ratio': self.metrics['errors'] / max(1, self.metrics['suggestions_generated']),
            'avg_response_time': round(avg_time, 3)
        }


# Initialize a singleton instance
ai_assistant_service = AIAssistantService()