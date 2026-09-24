import React, { useState } from 'react';
import { CheckCircle2, Plus, ArrowRight, UserPlus } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const PeopleSection = ({ searchQuery }) => {
  const { contacts, startPaymentFlow } = useApp();
  const [showAddContact, setShowAddContact] = useState(false);
  const [newContact, setNewContact] = useState({ name: '', phone: '', upiId: '' });

  const filteredContacts = contacts.filter(c =>
    c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.upiId.toLowerCase().includes(searchQuery.toLowerCase()) ||
    c.phone.includes(searchQuery)
  );

  return (
    <section id="people-section" className="py-2">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-base font-bold text-white tracking-tight font-heading">
          People
        </h2>
        <span className="text-xs text-blue-400 font-medium">Recent Payees</span>
      </div>

      <div className="grid grid-cols-4 sm:grid-cols-6 gap-3">
        {/* Add Contact button */}
        <div className="flex flex-col items-center">
          <button
            onClick={() => setShowAddContact(true)}
            className="w-14 h-14 rounded-full border-2 border-dashed border-slate-700 hover:border-blue-500 bg-slate-800/40 hover:bg-slate-800 text-slate-400 hover:text-blue-400 flex items-center justify-center transition-all cursor-pointer group"
          >
            <UserPlus className="w-5 h-5 group-hover:scale-110 transition-transform" />
          </button>
          <span className="mt-1.5 text-xs text-slate-400 font-medium text-center truncate max-w-[64px]">
            Add New
          </span>
        </div>

        {/* Contact list */}
        {filteredContacts.map((contact) => (
          <button
            key={contact.id}
            onClick={() => startPaymentFlow(contact)}
            className="flex flex-col items-center group cursor-pointer"
          >
            <div className="relative">
              <img
                src={contact.avatar}
                alt={contact.name}
                className="w-14 h-14 rounded-full object-cover ring-2 ring-slate-800 group-hover:ring-blue-500 group-hover:scale-105 transition-all shadow-md"
              />
              {contact.verified && (
                <div className="absolute -bottom-0.5 -right-0.5 bg-blue-600 rounded-full p-0.5 text-white ring-2 ring-slate-900">
                  <CheckCircle2 className="w-3 h-3 text-white" />
                </div>
              )}
            </div>
            <span className="mt-1.5 text-xs text-slate-200 group-hover:text-blue-400 font-medium text-center truncate max-w-[68px]">
              {contact.name.split(' ')[0]}
            </span>
            <span className="text-[10px] text-slate-500">
              ₹{contact.recentAmount}
            </span>
          </button>
        ))}
      </div>

      {/* Add Contact Modal */}
      {showAddContact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-3xl bg-slate-900 border border-slate-700/80 p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-1 font-heading">Add New Contact</h3>
            <p className="text-xs text-slate-400 mb-4">Save trusted recipient to fast-pay list.</p>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Full Name</label>
                <input
                  type="text"
                  placeholder="e.g. Maya Kapoor"
                  value={newContact.name}
                  onChange={(e) => setNewContact({ ...newContact, name: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-slate-800 border border-slate-700 text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Phone Number</label>
                <input
                  type="tel"
                  placeholder="+91 98111 22334"
                  value={newContact.phone}
                  onChange={(e) => setNewContact({ ...newContact, phone: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-slate-800 border border-slate-700 text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">UPI ID</label>
                <input
                  type="text"
                  placeholder="maya@senitenial"
                  value={newContact.upiId}
                  onChange={(e) => setNewContact({ ...newContact, upiId: e.target.value })}
                  className="w-full px-3.5 py-2 rounded-xl bg-slate-800 border border-slate-700 text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddContact(false)}
                  className="flex-1 py-2.5 rounded-xl bg-slate-800 text-slate-300 hover:bg-slate-700 font-medium text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (!newContact.name) return;
                    startPaymentFlow({
                      name: newContact.name,
                      phone: newContact.phone,
                      upiId: newContact.upiId || `${newContact.name.toLowerCase().replace(/\s+/g, '')}@senitenial`,
                      avatar: 'https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?auto=format&fit=crop&q=80&w=150'
                    });
                    setShowAddContact(false);
                  }}
                  className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs shadow-lg shadow-blue-600/30 transition-all cursor-pointer"
                >
                  Save & Pay
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
