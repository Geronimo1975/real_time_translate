// src/components/Dashboard.js
import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Card, Button, Table, Form, Modal, Badge, Alert, Tabs, Tab } from 'react-bootstrap';
import { FaPlus, FaEdit, FaTrash, FaLink, FaCopy, FaChartBar, FaHistory, FaCalendarPlus } from 'react-icons/fa';
import axios from 'axios';
import { useHistory } from 'react-router-dom';

// Chart component for usage statistics
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const Dashboard = () => {
  const history = useHistory();
  const [meetings, setMeetings] = useState([]);
  const [pastMeetings, setPastMeetings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showNewMeetingModal, setShowNewMeetingModal] = useState(false);
  const [copiedLink, setCopiedLink] = useState('');
  const [usageStats, setUsageStats] = useState([]);
  const [activeTab, setActiveTab] = useState('upcoming');
  
  // Form state for new meeting
  const [newMeeting, setNewMeeting] = useState({
    title: '',
    startTime: '',
    sourceLanguage: 'en',
    targetLanguage: 'ro',
    participantEmails: ''
  });
  
  // Load data on component mount
  useEffect(() => {
    fetchMeetings();
    fetchUsageStatistics();
  }, []);
  
  // Function to fetch meetings from API
  const fetchMeetings = async () => {
    try {
      setLoading(true);
      const token = localStorage.getItem('authToken');
      
      const response = await axios.get('/api/meetings/', {
        headers: {
          'Authorization': `Token ${token}`
        }
      });
      
      // Split meetings into upcoming and past
      const current = new Date();
      const upcoming = [];
      const past = [];
      
      response.data.forEach(meeting => {
        const meetingDate = new Date(meeting.start_time);
        if (meeting.status === 'completed' || meetingDate < current) {
          past.push(meeting);
        } else {
          upcoming.push(meeting);
        }
      });
      
      setMeetings(upcoming);
      setPastMeetings(past);
      setLoading(false);
    } catch (err) {
      setError('Eroare la încărcarea întâlnirilor. Vă rugăm încercați din nou.');
      setLoading(false);
      console.error('Error fetching meetings:', err);
    }
  };
  
  // Function to fetch usage statistics
  const fetchUsageStatistics = async () => {
    try {
      const token = localStorage.getItem('authToken');
      
      const response = await axios.get('/api/usage-statistics/', {
        headers: {
          'Authorization': `Token ${token}`
        }
      });
      
      setUsageStats(response.data);
    } catch (err) {
      console.error('Error fetching usage statistics:', err);
      // Don't set error state here to avoid overriding more important errors
    }
  };
  
  // Function to handle new meeting creation
  const handleCreateMeeting = async (e) => {
    e.preventDefault();
    
    try {
      const token = localStorage.getItem('authToken');
      
      // Format participant emails as array
      const participants = newMeeting.participantEmails
        .split(',')
        .map(email => email.trim())
        .filter(email => email);
      
      const response = await axios.post('/api/meetings/', {
        title: newMeeting.title,
        start_time: newMeeting.startTime,
        source_language: newMeeting.sourceLanguage,
        target_language: newMeeting.targetLanguage,
        participants: participants
      }, {
        headers: {
          'Authorization': `Token ${token}`
        }
      });
      
      // Add new meeting to state
      setMeetings([...meetings, response.data]);
      
      // Reset form and close modal
      setNewMeeting({
        title: '',
        startTime: '',
        sourceLanguage: 'en',
        targetLanguage: 'ro',
        participantEmails: ''
      });
      setShowNewMeetingModal(false);
      
      // Show confirmation (could use a toast notification here)
      setError('');
    } catch (err) {
      setError('Eroare la crearea întâlnirii. Verificați datele introduse.');
      console.error('Error creating meeting:', err);
    }
  };
  
  // Function to handle deleting a meeting
  const handleDeleteMeeting = async (meetingId) => {
    if (!window.confirm('Sigur doriți să ștergeți această întâlnire?')) {
      return;
    }
    
    try {
      const token = localStorage.getItem('authToken');
      
      await axios.delete(`/api/meetings/${meetingId}/`, {
        headers: {
          'Authorization': `Token ${token}`
        }
      });
      
      // Update meetings list
      setMeetings(meetings.filter(meeting => meeting.id !== meetingId));
      setPastMeetings(pastMeetings.filter(meeting => meeting.id !== meetingId));
      
      setError('');
    } catch (err) {
      setError('Eroare la ștergerea întâlnirii.');
      console.error('Error deleting meeting:', err);
    }
  };
  
  // Function to join a meeting
  const joinMeeting = (meetingId) => {
    history.push(`/meeting/${meetingId}`);
  };
  
  // Function to copy meeting link to clipboard
  const copyMeetingLink = (meetingId) => {
    const link = `${window.location.origin}/meeting/${meetingId}`;
    navigator.clipboard.writeText(link)
      .then(() => {
        setCopiedLink(meetingId);
        setTimeout(() => setCopiedLink(''), 2000);
      })
      .catch(err => {
        console.error('Could not copy link: ', err);
      });
  };
  
  // Placeholder usage data (in a real app, this would come from the API)
  const usageData = usageStats.length > 0 ? usageStats : [
    { name: 'Ian', minutes: 120 },
    { name: 'Feb', minutes: 180 },
    { name: 'Mar', minutes: 150 },
    { name: 'Apr', minutes: 210 },
    { name: 'Mai', minutes: 240 },
    { name: 'Iun', minutes: 190 }
  ];
  
  // Function to format date string
  const formatDate = (dateString) => {
    const options = { 
      year: 'numeric', 
      month: 'short', 
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    };
    return new Date(dateString).toLocaleDateString('ro-RO', options);
  };
  
  // Function to render status badge
  const renderStatusBadge = (status) => {
    let variant = 'secondary';
    let label = status;
    
    switch(status) {
      case 'scheduled':
        variant = 'info';
        label = 'Programat';
        break;
      case 'live':
        variant = 'success';
        label = 'În desfășurare';
        break;
      case 'completed':
        variant = 'secondary';
        label = 'Finalizat';
        break;
      case 'cancelled':
        variant = 'danger';
        label = 'Anulat';
        break;
      default:
        break;
    }
    
    return <Badge variant={variant}>{label}</Badge>;
  };
  
  return (
    <Container className="mt-4 mb-5">
      <Row className="mb-4">
        <Col>
          <h2>Dashboard Traducere</h2>
          <p className="text-muted">Gestionați sesiunile de traducere în timp real pentru întâlniri și interviuri.</p>
        </Col>
        <Col xs="auto">
          <Button 
            variant="primary" 
            onClick={() => setShowNewMeetingModal(true)}
          >
            <FaPlus className="mr-2" /> Întâlnire nouă
          </Button>
        </Col>
      </Row>
      
      {error && (
        <Row className="mb-4">
          <Col>
            <Alert variant="danger">{error}</Alert>
          </Col>
        </Row>
      )}
      
      <Row className="mb-4">
        <Col md={4}>
          <Card>
            <Card.Body>
              <h5 className="mb-3">Minute disponibile</h5>
              <div className="d-flex align-items-center">
                <h2 className="mb-0 mr-2">180</h2>
                <span className="text-muted">minute</span>
              </div>
              <div className="progress mt-3">
                <div 
                  className="progress-bar bg-success" 
                  role="progressbar" 
                  style={{ width: '60%' }} 
                  aria-valuenow="60" 
                  aria-valuemin="0" 
                  aria-valuemax="100"
                >
                  60%
                </div>
              </div>
              <div className="text-right mt-2">
                <small className="text-muted">Din 300 minute (plan Pro)</small>
              </div>
            </Card.Body>
            <Card.Footer>
              <Button variant="outline-primary" size="sm" className="w-100">
                Upgrade Plan
              </Button>
            </Card.Footer>
          </Card>
        </Col>
        
        <Col md={8}>
          <Card>
            <Card.Header>
              <h5 className="mb-0">Utilizare minute traducere</h5>
            </Card.Header>
            <Card.Body>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={usageData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="minutes" fill="#4e73df" name="Minute utilizate" />
                </BarChart>
              </ResponsiveContainer>
            </Card.Body>
          </Card>
        </Col>
      </Row>
      
      <Row>
        <Col>
          <Card>
            <Card.Header>
              <Tabs
                activeKey={activeTab}
                onSelect={(k) => setActiveTab(k)}
                className="mb-0"
              >
                <Tab eventKey="upcoming" title="Întâlniri programate">
                  <div className="pt-3">
                    {loading ? (
                      <p className="text-center">Se încarcă...</p>
                    ) : meetings.length === 0 ? (
                      <p className="text-center text-muted">Nu aveți întâlniri programate. Creați una acum!</p>
                    ) : (
                      <Table responsive hover>
                        <thead>
                          <tr>
                            <th>Titlu</th>
                            <th>Data</th>
                            <th>Stare</th>
                            <th>Limbă sursă</th>
                            <th>Limbă țintă</th>
                            <th>Acțiuni</th>
                          </tr>
                        </thead>
                        <tbody>
                          {meetings.map(meeting => (
                            <tr key={meeting.id}>
                              <td>{meeting.title}</td>
                              <td>{formatDate(meeting.start_time)}</td>
                              <td>{renderStatusBadge(meeting.status)}</td>
                              <td>{meeting.source_language}</td>
                              <td>{meeting.target_language}</td>
                              <td>
                                <Button 
                                  variant="primary" 
                                  size="sm" 
                                  className="mr-2"
                                  onClick={() => joinMeeting(meeting.id)}
                                >
                                  <FaLink className="mr-1" /> Alătură-te
                                </Button>
                                <Button 
                                  variant="light" 
                                  size="sm" 
                                  className="mr-2"
                                  onClick={() => copyMeetingLink(meeting.id)}
                                >
                                  <FaCopy className="mr-1" /> 
                                  {copiedLink === meeting.id ? 'Copiat!' : 'Copiază link'}
                                </Button>
                                <Button 
                                  variant="danger" 
                                  size="sm"
                                  onClick={() => handleDeleteMeeting(meeting.id)}
                                >
                                  <FaTrash />
                                </Button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                    )}
                  </div>
                </Tab>
                <Tab eventKey="past" title="Întâlniri anterioare">
                  <div className="pt-3">
                    {loading ? (
                      <p className="text-center">Se încarcă...</p>
                    ) : pastMeetings.length === 0 ? (
                      <p className="text-center text-muted">Nu aveți întâlniri anterioare.</p>
                    ) : (
                      <Table responsive hover>
                        <thead>
                          <tr>
                            <th>Titlu</th>
                            <th>Data</th>
                            <th>Durată</th>
                            <th>Participanți</th>
                            <th>Acțiuni</th>
                          </tr>
                        </thead>
                        <tbody>
                          {pastMeetings.map(meeting => (
                            <tr key={meeting.id}>
                              <td>{meeting.title}</td>
                              <td>{formatDate(meeting.start_time)}</td>
                              <td>{meeting.duration || '45'} min</td>
                              <td>{meeting.participants_count || '3'}</td>
                              <td>
                                <Button 
                                  variant="info" 
                                  size="sm" 
                                  className="mr-2"
                                >
                                  <FaHistory className="mr-1" /> Transcriere
                                </Button>
                                <Button 
                                  variant="danger" 
                                  size="sm"
                                  onClick={() => handleDeleteMeeting(meeting.id)}
                                >
                                  <FaTrash />
                                </Button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                    )}
                  </div>
                </Tab>
              </Tabs>
            </Card.Header>
          </Card>
        </Col>
      </Row>
      
      {/* New Meeting Modal */}
      <Modal 
        show={showNewMeetingModal} 
        onHide={() => setShowNewMeetingModal(false)}
        backdrop="static"
        size="lg"
      >
        <Modal.Header closeButton>
          <Modal.Title>Programare întâlnire nouă</Modal.Title>
        </Modal.Header>
        <Form onSubmit={handleCreateMeeting}>
          <Modal.Body>
            <Form.Group>
              <Form.Label>Titlu întâlnire</Form.Label>
              <Form.Control 
                type="text" 
                placeholder="Ex: Interviu dezvoltator Python"
                value={newMeeting.title}
                onChange={(e) => setNewMeeting({...newMeeting, title: e.target.value})}
                required
              />
            </Form.Group>
            
            <Form.Group>
              <Form.Label>Data și ora</Form.Label>
              <Form.Control 
                type="datetime-local" 
                value={newMeeting.startTime}
                onChange={(e) => setNewMeeting({...newMeeting, startTime: e.target.value})}
                required
              />
            </Form.Group>
            
            <Row>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Limbă sursă</Form.Label>
                  <Form.Control 
                    as="select"
                    value={newMeeting.sourceLanguage}
                    onChange={(e) => setNewMeeting({...newMeeting, sourceLanguage: e.target.value})}
                  >
                    <option value="en">Engleză</option>
                    <option value="de">Germană</option>
                    <option value="fr">Franceză</option>
                    <option value="es">Spaniolă</option>
                    <option value="it">Italiană</option>
                    <option value="ro">Română</option>
                  </Form.Control>
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Limbă țintă</Form.Label>
                  <Form.Control 
                    as="select"
                    value={newMeeting.targetLanguage}
                    onChange={(e) => setNewMeeting({...newMeeting, targetLanguage: e.target.value})}
                  >
                    <option value="ro">Română</option>
                    <option value="en">Engleză</option>
                    <option value="de">Germană</option>
                    <option value="fr">Franceză</option>
                    <option value="es">Spaniolă</option>
                    <option value="it">Italiană</option>
                  </Form.Control>
                </Form.Group>
              </Col>
            </Row>
            
            <Form.Group>
              <Form.Label>Email-uri participanți (opțional, separate prin virgulă)</Form.Label>
              <Form.Control 
                as="textarea" 
                rows={3}
                placeholder="Ex: john@example.com, alice@example.com"
                value={newMeeting.participantEmails}
                onChange={(e) => setNewMeeting({...newMeeting, participantEmails: e.target.value})}
              />
              <Form.Text className="text-muted">
                Participanții vor primi un email cu link-ul pentru întâlnire.
              </Form.Text>
            </Form.Group>
          </Modal.Body>
          <Modal.Footer>
            <Button variant="secondary" onClick={() => setShowNewMeetingModal(false)}>
              Anulează
            </Button>
            <Button variant="primary" type="submit">
              <FaCalendarPlus className="mr-2" /> Creează întâlnire
            </Button>
          </Modal.Footer>
        </Form>
      </Modal>
    </Container>
  );
};

export default Dashboard;