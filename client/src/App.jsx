import { Routes, Route, NavLink } from 'react-router-dom';
import SendFax from './pages/SendFax';
import FaxHistory from './pages/FaxHistory';
import Contacts from './pages/Contacts';
import Dashboard from './pages/Dashboard';
import AuditLog from './pages/AuditLog';
import './App.css';

export default function App() {
  return (
    <div className="app">
      <nav className="sidebar">
        <div className="logo">Fax Manager</div>
        <NavLink to="/" end>Dashboard</NavLink>
        <NavLink to="/send">Send Fax</NavLink>
        <NavLink to="/history">Fax History</NavLink>
        <NavLink to="/contacts">Contacts</NavLink>
        <NavLink to="/audit">Audit Log</NavLink>
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/send" element={<SendFax />} />
          <Route path="/history" element={<FaxHistory />} />
          <Route path="/contacts" element={<Contacts />} />
          <Route path="/audit" element={<AuditLog />} />
        </Routes>
      </main>
    </div>
  );
}
