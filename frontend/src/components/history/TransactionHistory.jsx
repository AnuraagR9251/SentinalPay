import React, { useState } from 'react';
import {
  Search,
  ArrowUpRight,
  ArrowDownLeft,
  Filter,
  Download,
  Receipt,
  PieChart,
  Calendar,
  Sparkles
} from 'lucide-react';
import { useApp } from '../../context/AppContext';

export const TransactionHistory = () => {
  const { transactions, setReceiptModal, user } = useApp();
  const [filterType, setFilterType] = useState('all'); // all, debit, credit, bills, rewards
  const [search, setSearch] = useState('');

  const filteredTransactions = transactions.filter((tx) => {
    const matchesSearch =
      tx.title.toLowerCase().includes(search.toLowerCase()) ||
      tx.category.toLowerCase().includes(search.toLowerCase()) ||
      (tx.note && tx.note.toLowerCase().includes(search.toLowerCase())) ||
      tx.utr.toLowerCase().includes(search.toLowerCase());

    if (!matchesSearch) return false;

    if (filterType === 'all') return true;
    if (filterType === 'debit') return tx.type === 'debit';
    if (filterType === 'credit') return tx.type === 'credit';
    if (filterType === 'bills') return tx.category.toLowerCase().includes('bill');
    if (filterType === 'rewards') return tx.category.toLowerCase().includes('reward');
    return true;
  });

  // Calculate totals
  const totalDebit = transactions
    .filter(t => t.type === 'debit')
    .reduce((sum, t) => sum + t.amount, 0);

  const totalCredit = transactions
    .filter(t => t.type === 'credit')
    .reduce((sum, t) => sum + t.amount, 0);

  const handleExportStatement = () => {
    const csvContent = "data:text/csv;charset=utf-8," +
      ["Date,Title,UPI ID,Type,Amount,Method,UTR", ...transactions.map(t =>
        `"${t.timestamp}","${t.title}","${t.upiId}","${t.type}",${t.amount},"${t.method}","${t.utr}"`
      )].join("\n");

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `senitenial_statement_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto px-4 py-4 animate-fade-in">
      {/* Header Banner */}
      <div className="rounded-3xl p-6 bg-gradient-to-br from-slate-900 via-indigo-950 to-blue-950 border border-blue-500/20 shadow-xl flex items-center justify-between">
        <div>
          <span className="text-xs uppercase font-bold tracking-wider text-blue-400">
            Audit Ledger
          </span>
          <h1 className="text-2xl font-black text-white font-heading mt-1">
            Transaction History
          </h1>
          <p className="text-xs text-slate-300 mt-1 max-w-md">
            Complete cryptographic audit trail of all peer transfers, bill settlements, and rewards.
          </p>
        </div>

        <button
          onClick={handleExportStatement}
          className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-2xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-semibold cursor-pointer transition-colors"
          title="Download CSV Statement"
        >
          <Download className="w-4 h-4 text-blue-400" />
          <span className="hidden sm:inline">Export CSV</span>
        </button>
      </div>

      {/* Spending Summary Cards */}
      <div className="grid grid-cols-2 gap-3">
        <div className="p-4 rounded-2xl bg-slate-800/40 border border-slate-700/60">
          <div className="flex items-center gap-2 text-rose-400 text-xs font-semibold mb-1">
            <ArrowUpRight className="w-4 h-4" />
            <span>Total Debited</span>
          </div>
          <div className="text-xl sm:text-2xl font-black text-white font-heading">
            {user.currency}{totalDebit.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <p className="text-[10px] text-slate-400 mt-0.5">Purchases, bills & transfers</p>
        </div>

        <div className="p-4 rounded-2xl bg-slate-800/40 border border-slate-700/60">
          <div className="flex items-center gap-2 text-emerald-400 text-xs font-semibold mb-1">
            <ArrowDownLeft className="w-4 h-4" />
            <span>Total Credited</span>
          </div>
          <div className="text-xl sm:text-2xl font-black text-white font-heading">
            {user.currency}{totalCredit.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
          </div>
          <p className="text-[10px] text-slate-400 mt-0.5">Cashbacks, refunds & received</p>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="space-y-3">
        <div className="relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
          <input
            type="text"
            placeholder="Search by payee, category, note or UTR..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2.5 rounded-2xl bg-slate-800/80 border border-slate-700/80 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* Filter Pills */}
        <div className="flex gap-1.5 overflow-x-auto no-scrollbar py-1">
          {[
            { id: 'all', label: 'All Transfers' },
            { id: 'debit', label: 'Paid (Debits)' },
            { id: 'credit', label: 'Received (Credits)' },
            { id: 'bills', label: 'Bills & Utilities' },
            { id: 'rewards', label: 'Cashbacks & Rewards' }
          ].map(f => (
            <button
              key={f.id}
              onClick={() => setFilterType(f.id)}
              className={`px-3 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
                filterType === f.id
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'bg-slate-800 text-slate-400 hover:text-white'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Transaction List */}
      <div className="space-y-2">
        {filteredTransactions.length === 0 ? (
          <div className="py-12 text-center text-slate-500 text-xs">
            No matching transactions found.
          </div>
        ) : (
          filteredTransactions.map((tx) => {
            const isDebit = tx.type === 'debit';
            return (
              <div
                key={tx.id}
                onClick={() => setReceiptModal({ isOpen: true, transaction: tx })}
                className="p-3.5 rounded-2xl bg-slate-800/40 hover:bg-slate-800/80 border border-slate-700/60 hover:border-slate-600 transition-all flex items-center justify-between cursor-pointer group"
              >
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-2xl flex items-center justify-center ${
                    isDebit
                      ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                      : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  }`}>
                    {isDebit ? <ArrowUpRight className="w-5 h-5" /> : <ArrowDownLeft className="w-5 h-5" />}
                  </div>

                  <div>
                    <h4 className="text-sm font-bold text-white group-hover:text-blue-400 transition-colors">
                      {tx.title}
                    </h4>
                    <p className="text-[11px] text-slate-400">
                      {tx.timestamp} • <span className="text-slate-300">{tx.category}</span>
                    </p>
                  </div>
                </div>

                <div className="text-right">
                  <div className={`text-sm sm:text-base font-bold font-heading ${
                    isDebit ? 'text-white' : 'text-emerald-400'
                  }`}>
                    {isDebit ? '-' : '+'}{user.currency}{tx.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </div>
                  <span className="text-[10px] text-slate-500 font-mono">
                    {tx.method.split(' ')[0]}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
