import { Routes, Route, NavLink } from 'react-router-dom';
import SendFax from './pages/SendFax';
import FaxHistory from './pages/FaxHistory';
import Contacts from './pages/Contacts';
import './App.css';

export default function App() {
  return (
    <div className="app">
      <nav className="sidebar">
        <div className="logo">Fax Manager</div>
        <NavLink to="/" end>Send Fax</NavLink>
        <NavLink to="/history">Fax History</NavLink>
        <NavLink to="/contacts">Contacts</NavLink>
      </nav>
      <main className="content">
        <Routes>
          <Route path="/" element={<SendFax />} />
          <Route path="/history" element={<FaxHistory />} />
          <Route path="/contacts" element={<Contacts />} />
        </Routes>
      </main>
    </div>
  );
}
