# meetings/models.py
from django.db import models
from accounts.models import User

class Meeting(models.Model):
    STATUS_CHOICES = (
        ('scheduled', 'Programat'),
        ('live', 'În desfășurare'),
        ('completed', 'Finalizat'),
        ('cancelled', 'Anulat'),
    )
    
    title = models.CharField(max_length=255)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_meetings')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    source_language = models.CharField(max_length=10, default='en')
    target_language = models.CharField(max_length=10, default='ro')
    meeting_url = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.title

class MeetingParticipant(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    name = models.CharField(max_length=255)
    preferred_language = models.CharField(max_length=10, default='ro')
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.name} - {self.meeting.title}"

class Transcript(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='transcripts')
    participant = models.ForeignKey(MeetingParticipant, on_delete=models.CASCADE, related_name='speech_segments')
    original_text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    source_language = models.CharField(max_length=10)
    
    def __str__(self):
        return f"Transcriere: {self.meeting.title} - {self.participant.name}"

class Translation(models.Model):
    transcript = models.ForeignKey(Transcript, on_delete=models.CASCADE, related_name='translations')
    translated_text = models.TextField()
    target_language = models.CharField(max_length=10)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Traducere ({self.target_language}): {self.transcript.meeting.title}"

class AISuggestion(models.Model):
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name='ai_suggestions')
    for_participant = models.ForeignKey(MeetingParticipant, on_delete=models.CASCADE, related_name='received_suggestions')
    suggested_text = models.TextField()
    context = models.TextField()  # Contextul care a generat sugestia
    timestamp = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Sugestie pentru: {self.for_participant.name}"