import React, { useState } from 'react';
import { Users, Plus, CheckCircle, ArrowRight, DollarSign, Calculator, Send } from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const SplitExpenses = () => {
  const { splits, addSplitGroup, contacts, user, startPaymentFlow } = useApp();
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [title, setTitle] = useState('');
  const [totalAmount, setTotalAmount] = useState('');
  const [selectedFriends, setSelectedFriends] = useState([]);

  const toggleFriend = (name) => {
    if (selectedFriends.includes(name)) {
      setSelectedFriends(selectedFriends.filter(f => f !== name));
    } else {
      setSelectedFriends([...selectedFriends, name]);
    }
  };

  const handleCreateSplit = (e) => {
    e.preventDefault();
    const amt = parseFloat(totalAmount);
    if (!title || isNaN(amt) || amt <= 0 || selectedFriends.length === 0) return;

    const totalParticipants = selectedFriends.length + 1; // friends + current user
    const share = Math.round(amt / totalParticipants);

    const newSplit = {
      id: `split-${Date.now()}`,
      title,
      totalAmount: amt,
      myShare: share,
      members: ["Aarav (You)", ...selectedFriends],
      status: "Active",
      settled: false,
      category: "Group Expense"
    };

    addSplitGroup(newSplit);
    setShowCreateModal(false);
    setTitle('');
    setTotalAmount('');
    setSelectedFriends([]);
  };

  const handleSettle = (split) => {
    startPaymentFlow({
      name: split.title,
      upiId: "settle@senitenial",
      avatar: null
    }, split.myShare, 'Split Settlement');
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto px-4 py-4 animate-fade-in">
      {/* Banner */}
      <div className="rounded-3xl p-6 bg-gradient-to-br from-indigo-900/50 via-slate-900 to-purple-950 border border-indigo-500/20 shadow-xl flex items-center justify-between">
        <div>
          <span className="text-xs uppercase font-bold tracking-wider text-indigo-400">
            Split & Settle Expenses
          </span>
          <h1 className="text-2xl font-black text-white font-heading mt-1">
            Group Bills & Splits
          </h1>
          <p className="text-xs text-slate-300 mt-1 max-w-md">
            Split dinners, trips, and flat rent with friends. Zero awkwardness, instant auto-settlement.
          </p>
        </div>

        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2.5 rounded-2xl bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-lg shadow-blue-600/30 transition-all cursor-pointer whitespace-nowrap"
        >
          <Plus className="w-4 h-4" />
          <span>New Split</span>
        </button>
      </div>

      {/* Active Splits List */}
      <div className="space-y-3">
        <h2 className="text-base font-bold text-white font-heading">Active Group Splits</h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {splits.map((split) => (
            <div
              key={split.id}
              className="p-4 rounded-2xl bg-slate-800/50 border border-slate-700/70 hover:border-slate-600 transition-all flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-white font-heading">{split.title}</h3>
                    <p className="text-[11px] text-slate-400 mt-0.5">
                      {split.members.join(', ')}
                    </p>
                  </div>
                  <span className="px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 text-[10px] font-bold">
                    {split.category}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 mt-4 p-3 rounded-xl bg-slate-900/80 border border-slate-800">
                  <div>
                    <span className="text-[10px] text-slate-400">Total Bill</span>
                    <p className="text-base font-extrabold text-white">
                      {user.currency}{split.totalAmount.toLocaleString('en-IN')}
                    </p>
                  </div>
                  <div>
                    <span className="text-[10px] text-indigo-400 font-semibold">Your Share</span>
                    <p className="text-base font-extrabold text-emerald-400">
                      {user.currency}{split.myShare.toLocaleString('en-IN')}
                    </p>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-700/50 flex items-center justify-between">
                <span className="text-xs text-slate-400">
                  {split.settled ? "Settled" : "Pending settlement"}
                </span>

                <button
                  onClick={() => handleSettle(split)}
                  className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-bold text-xs shadow-md shadow-emerald-600/30 transition-all cursor-pointer flex items-center gap-1.5"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>Settle {user.currency}{split.myShare}</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Create Split Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-3xl bg-slate-900 border border-slate-700/80 p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-1 font-heading">Start a New Bill Split</h3>
            <p className="text-xs text-slate-400 mb-4">Calculate and split effortlessly with friends.</p>

            <form onSubmit={handleCreateSplit} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Expense Title</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Goa Dinner or Netflix Family"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full px-3.5 py-2 rounded-xl bg-slate-800 border border-slate-700 text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Total Bill Amount</label>
                <div className="relative">
                  <span className="absolute left-3 top-2.5 text-slate-400 text-sm font-bold">{user.currency}</span>
                  <input
                    type="number"
                    required
                    placeholder="2500"
                    value={totalAmount}
                    onChange={(e) => setTotalAmount(e.target.value)}
                    className="w-full pl-8 pr-3.5 py-2 rounded-xl bg-slate-800 border border-slate-700 text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Select Friends</label>
                <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto">
                  {contacts.map((contact) => {
                    const isSelected = selectedFriends.includes(contact.name);
                    return (
                      <button
                        type="button"
                        key={contact.id}
                        onClick={() => toggleFriend(contact.name)}
                        className={`px-2.5 py-1 rounded-xl text-xs font-medium transition-all cursor-pointer ${
                          isSelected
                            ? 'bg-blue-600 text-white'
                            : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                        }`}
                      >
                        {isSelected ? '✓ ' : '+ '}{contact.name}
                      </button>
                    );
                  })}
                </div>
              </div>

              {totalAmount && selectedFriends.length > 0 && (
                <div className="p-3 rounded-xl bg-blue-950/60 border border-blue-500/30 text-xs text-blue-200">
                  Per person share: <span className="font-bold text-white">₹{Math.round(parseFloat(totalAmount) / (selectedFriends.length + 1))}</span> ({selectedFriends.length + 1} people)
                </div>
              )}

              <div className="flex gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="flex-1 py-2.5 rounded-xl bg-slate-800 text-slate-300 hover:bg-slate-700 font-medium text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!title || !totalAmount || selectedFriends.length === 0}
                  className="flex-1 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium text-xs shadow-lg shadow-blue-600/30 transition-all cursor-pointer"
                >
                  Create Split
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
