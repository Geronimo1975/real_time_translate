# accounts/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    preferred_language = models.CharField(max_length=10, default='ro')
    is_premium = models.BooleanField(default=False)
    available_minutes = models.IntegerField(default=60)  # Plan gratuit - 60 minute
    
    def __str__(self):
        return self.email

