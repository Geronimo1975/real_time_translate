// src/components/TranslationMeeting.js
import React, { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { Button, Card, Container, Row, Col, Form, Alert, Badge, ListGroup, Tab, Tabs } from 'react-bootstrap';
import { FaMicrophone, FaMicrophoneSlash, FaComments, FaRobot, FaCog, FaUsers } from 'react-icons/fa';

const TranslationMeeting = () => {
  const { meetingId } = useParams();
  const [isConnected, setIsConnected] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [messages, setMessages] = useState([]);
  const [participants, setParticipants] = useState([]);
  const [chatMessage, setChatMessage] = useState('');
  const [suggestions, setSuggestions] = useState([]);
  const [meetingInfo, setMeetingInfo] = useState(null);
  const [error, setError] = useState('');
  const [preferredLanguage, setPreferredLanguage] = useState('ro');
  const [userRole, setUserRole] = useState('interviewee');
  
  const socket = useRef(null);
  const mediaRecorder = useRef(null);
  const messagesEndRef = useRef(null);
  
  // Conectare la WebSocket
  useEffect(() => {
    // Obține token de autentificare din localStorage
    const token = localStorage.getItem('authToken') || '';
    
    // Construiește URL-ul WebSocket
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/meeting/${meetingId}/?token=${token}`;
    
    // Inițializare WebSocket
    socket.current = new WebSocket(wsUrl);
    
    socket.current.onopen = () => {
      setIsConnected(true);
      setError('');
      
      // Cerere informații despre meeting
      socket.current.send(JSON.stringify({
        type: 'request_meeting_info'
      }));
      
      // Cerere listă participanți
      socket.current.send(JSON.stringify({
        type: 'request_participants'
      }));
    };
    
    socket.current.onclose = (e) => {
      setIsConnected(false);
      if (e.code !== 1000) {
        setError('Conexiunea la server a fost închisă. Încercați să reîmprospătați pagina.');
      }
    };
    
    socket.current.onerror = () => {
      setError('Eroare la conectare cu serverul WebSocket.');
      setIsConnected(false);
    };
    
    socket.current.onmessage = (e) => {
      const data = JSON.parse(e.data);
      handleWebSocketMessage(data);
    };
    
    // Curățare la deconectare
    return () => {
      if (socket.current) {
        socket.current.close();
      }
      
      if (mediaRecorder.current && mediaRecorder.current.state === 'recording') {
        mediaRecorder.current.stop();
      }
    };
  }, [meetingId]);
  
  // Scroll automat la mesaje noi
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);
  
  // Gestionare mesaje primite prin WebSocket
  const handleWebSocketMessage = (data) => {
    switch (data.type) {
      case 'speech':
      case 'chat':
        const translation = data.translations[preferredLanguage] || data.original_text;
        
        setMessages(prev => [...prev, {
          id: Date.now(),
          type: data.type,
          sender: {
            id: data.participant_id,
            name: data.name
          },
          originalText: data.original_text,
          originalLanguage: data.original_language,
          translatedText: translation,
          timestamp: data.timestamp || new Date().toISOString()
        }]);
        break;
        
      case 'meeting_info':
        setMeetingInfo(data.meeting);
        break;
        
      case 'participants_list':
        setParticipants(data.participants);
        break;
        
      case 'participant_joined':
        setParticipants(prev => {
          if (!prev.find(p => p.id === data.participant_id)) {
            return [...prev, { 
              id: data.participant_id, 
              name: data.name 
            }];
          }
          return prev;
        });
        
        setMessages(prev => [...prev, {
          id: Date.now(),
          type: 'system',
          message: `${data.name} s-a alăturat întâlnirii.`
        }]);
        break;
        
      case 'participant_left':
        setMessages(prev => [...prev, {
          id: Date.now(),
          type: 'system',
          message: `${data.name} a părăsit întâlnirea.`
        }]);
        break;
        
      case 'suggestions':
        setSuggestions(data.suggestions);
        break;
        
      default:
        console.log('Mesaj necunoscut:', data);
    }
  };
  
  // Inițiere/Oprire înregistrare audio
  const toggleRecording = async () => {
    if (isRecording) {
      // Oprire înregistrare
      if (mediaRecorder.current && mediaRecorder.current.state === 'recording') {
        mediaRecorder.current.stop();
      }
      setIsRecording(false);
      return;
    }
    
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      
      mediaRecorder.current = new MediaRecorder(stream);
      
      // Setare intervale pentru trimitere date audio (la fiecare 2 secunde)
      const audioChunks = [];
      
      mediaRecorder.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunks.push(event.data);
        }
      };
      
      mediaRecorder.current.onstop = () => {
        // Eliberare stream audio
        stream.getTracks().forEach(track => track.stop());
      };
      
      // Procesare și trimitere date audio la intervale regulate
      const sendInterval = setInterval(() => {
        if (audioChunks.length > 0 && socket.current && socket.current.readyState === WebSocket.OPEN) {
          const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
          audioChunks.length = 0; // Golire array
          
          // Convertire Blob în base64 pentru a putea fi trimis prin WebSocket
          const reader = new FileReader();
          reader.onloadend = () => {
            const base64Audio = reader.result.split(',')[1]; // Elimină prefix MIME
            
            // Trimitere date audio prin WebSocket
            socket.current.send(JSON.stringify({
              type: 'speech',
              audio_data: base64Audio,
              language: navigator.language || 'en-US', // Utilizăm limba browserului
              timestamp: new Date().toISOString()
            }));
          };
          reader.readAsDataURL(audioBlob);
        }
      }, 2000); // Trimitere la fiecare 2 secunde
      
      mediaRecorder.current.onstart = () => {
        setIsRecording(true);
      };
      
      mediaRecorder.current.onerror = (event) => {
        console.error('Eroare înregistrare:', event.error);
        clearInterval(sendInterval);
        setIsRecording(false);
        setError('Eroare la înregistrarea audio. Verificați permisiunile microfonului.');
      };
      
      // Oprire înregistrare și interval la închiderea sesiunii
      mediaRecorder.current.addEventListener('stop', () => {
        clearInterval(sendInterval);
      });
      
      // Pornire înregistrare
      mediaRecorder.current.start(100); // Colectăm date la fiecare 100ms
      
    } catch (err) {
      console.error('Eroare la accesarea microfonului:', err);
      setError('Nu s-a putut accesa microfonul. Verificați permisiunile browserului.');
    }
  };
  
  // Trimitere mesaj din chat
  const sendChatMessage = (e) => {
    e.preventDefault();
    
    if (!chatMessage.trim() || !socket.current || socket.current.readyState !== WebSocket.OPEN) {
      return;
    }
    
    socket.current.send(JSON.stringify({
      type: 'chat_message',
      message: chatMessage,
      language: preferredLanguage,
      timestamp: new Date().toISOString()
    }));
    
    setChatMessage('');
  };
  
  // Generare sugestii AI
  const requestSuggestions = () => {
    // Construim contextul din ultimele 5 mesaje
    const context = messages
      .filter(m => m.type !== 'system')
      .slice(-5)
      .map(m => `${m.sender?.name || 'System'}: ${m.translatedText || m.message}`)
      .join('\n');
    
    socket.current.send(JSON.stringify({
      type: 'request_suggestions',
      context,
      language: preferredLanguage,
      meeting_type: meetingInfo?.meeting_type || 'interview',
      user_role: userRole
    }));
  };
  
  // Utilizare sugestie ca mesaj
  const useSuggestion = (suggestion) => {
    setChatMessage(suggestion);
  };
  
  // Render mesaje
  const renderMessages = () => {
    return messages.map(msg => {
      if (msg.type === 'system') {
        return (
          <div key={msg.id} className="system-message text-center my-2">
            <small className="text-muted">{msg.message}</small>
          </div>
        );
      }
      
      const isCurrentUser = participants.find(p => 
        p.id === msg.sender?.id
      )?.name === localStorage.getItem('userName');
      
      return (
        <Card 
          key={msg.id} 
          className={`my-2 ${isCurrentUser ? 'ml-auto' : 'mr-auto'}`}
          style={{ 
            maxWidth: '80%', 
            backgroundColor: isCurrentUser ? '#e3f2fd' : '#fff',
            alignSelf: isCurrentUser ? 'flex-end' : 'flex-start'
          }}
        >
          <Card.Body>
            <div className="d-flex justify-content-between align-items-center mb-2">
              <small className="font-weight-bold">{msg.sender?.name || 'Unknown'}</small>
              <Badge variant="info">{msg.type === 'speech' ? 'Voice' : 'Chat'}</Badge>
            </div>
            <Card.Text>{msg.translatedText}</Card.Text>
            {msg.originalText !== msg.translatedText && (
              <div className="mt-2 text-muted">
                <small>Original ({msg.originalLanguage}): {msg.originalText}</small>
              </div>
            )}
          </Card.Body>
          <Card.Footer className="text-muted">
            <small>{new Date(msg.timestamp).toLocaleTimeString()}</small>
          </Card.Footer>
        </Card>
      );
    });
  };
  
  return (
    <Container fluid className="mt-4 mb-5">
      {error && <Alert variant="danger">{error}</Alert>}
      
      <Row>
        <Col md={9}>
          <Card className="mb-4">
            <Card.Header className="d-flex justify-content-between align-items-center">
              <h5>{meetingInfo?.title || 'Sesiune de traducere'}</h5>
              <Badge variant={isConnected ? 'success' : 'danger'}>
                {isConnected ? 'Conectat' : 'Deconectat'}
              </Badge>
            </Card.Header>
            
            <Card.Body style={{ height: '60vh', overflowY: 'auto' }}>
              <div className="d-flex flex-column">
                {renderMessages()}
                <div ref={messagesEndRef} />
              </div>
            </Card.Body>
            
            <Card.Footer>
              <Form onSubmit={sendChatMessage}>
                <Row>
                  <Col md={1} className="d-flex align-items-center justify-content-center">
                    <Button 
                      variant={isRecording ? 'danger' : 'outline-primary'} 
                      onClick={toggleRecording}
                      disabled={!isConnected}
                      className="rounded-circle p-2"
                    >
                      {isRecording ? <FaMicrophoneSlash /> : <FaMicrophone />}
                    </Button>
                  </Col>
                  <Col md={9}>
                    <Form.Control
                      type="text"
                      placeholder="Scrieți un mesaj..."
                      value={chatMessage}
                      onChange={(e) => setChatMessage(e.target.value)}
                      disabled={!isConnected}
                    />
                  </Col>
                  <Col md={2}>
                    <Button 
                      type="submit" 
                      variant="primary" 
                      className="w-100"
                      disabled={!isConnected || !chatMessage.trim()}
                    >
                      <FaComments className="mr-2" /> Trimite
                    </Button>
                  </Col>
                </Row>
              </Form>
            </Card.Footer>
          </Card>
        </Col>
        
        <Col md={3}>
          <Tabs defaultActiveKey="suggestions" className="mb-3">
            <Tab eventKey="suggestions" title={<><FaRobot /> Sugestii</>}>
              <Card className="mb-3">
                <Card.Header className="d-flex justify-content-between align-items-center">
                  <h6>Sugestii de răspuns</h6>
                  <Button 
                    size="sm" 
                    variant="outline-primary"
                    onClick={requestSuggestions}
                    disabled={!isConnected || messages.length < 2}
                  >
                    Generează
                  </Button>
                </Card.Header>
                <ListGroup variant="flush">
                  {suggestions.length > 0 ? (
                    suggestions.map((suggestion, index) => (
                      <ListGroup.Item 
                        key={index}
                        action
                        onClick={() => useSuggestion(suggestion)}
                        className="text-truncate"
                      >
                        {suggestion}
                      </ListGroup.Item>
                    ))
                  ) : (
                    <ListGroup.Item className="text-center text-muted">
                      Apăsați pe "Generează" pentru sugestii
                    </ListGroup.Item>
                  )}
                </ListGroup>
              </Card>
            </Tab>
            
            <Tab eventKey="participants" title={<><FaUsers /> Participanți</>}>
              <Card>
                <Card.Header>
                  <h6>Participanți ({participants.length})</h6>
                </Card.Header>
                <ListGroup variant="flush">
                  {participants.map(participant => (
                    <ListGroup.Item key={participant.id}>
                      {participant.name}
                      {participant.preferred_language && (
                        <Badge variant="info" className="ml-2">
                          {participant.preferred_language}
                        </Badge>
                      )}
                    </ListGroup.Item>
                  ))}
                </ListGroup>
              </Card>
            </Tab>
            
            <Tab eventKey="settings" title={<><FaCog /> Setări</>}>
              <Card>
                <Card.Header>
                  <h6>Preferințe</h6>
                </Card.Header>
                <Card.Body>
                  <Form.Group>
                    <Form.Label>Limba preferată</Form.Label>
                    <Form.Control 
                      as="select"
                      value={preferredLanguage}
                      onChange={(e) => setPreferredLanguage(e.target.value)}
                    >
                      <option value="ro">Română</option>
                      <option value="en">Engleză</option>
                      <option value="de">Germană</option>
                      <option value="fr">Franceză</option>
                      <option value="es">Spaniolă</option>
                      <option value="it">Italiană</option>
                    </Form.Control>
                  </Form.Group>
                  
                  <Form.Group>
                    <Form.Label>Rol în conversație</Form.Label>
                    <Form.Control 
                      as="select"
                      value={userRole}
                      onChange={(e) => setUserRole(e.target.value)}
                    >
                      <option value="interviewee">Candidat (Intervievat)</option>
                      <option value="interviewer">Intervievator</option>
                      <option value="participant">Participant întâlnire</option>
                      <option value="host">Gazdă întâlnire</option>
                    </Form.Control>
                  </Form.Group>
                </Card.Body>
              </Card>
            </Tab>
          </Tabs>
        </Col>
      </Row>
    </Container>
  );
};

export default TranslationMeeting;