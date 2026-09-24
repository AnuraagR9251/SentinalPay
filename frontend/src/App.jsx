import React, { useState } from 'react';
import { AppProvider, useApp } from './context/AppContext';
import { Header } from './components/common/Header';
import { Navbar } from './components/common/Navbar';
import { DeviceFrame } from './components/common/DeviceFrame';
import { BalanceCard } from './components/home/BalanceCard';
import { QuickActions } from './components/home/QuickActions';
import { PeopleSection } from './components/home/PeopleSection';
import { BusinessesSection } from './components/home/BusinessesSection';
import { RewardsPreview } from './components/home/RewardsPreview';
import { BillsHub } from './components/bills/BillsHub';
import { SplitExpenses } from './components/split/SplitExpenses';
import { CardsManager } from './components/cards/CardsManager';
import { TransactionHistory } from './components/history/TransactionHistory';

// Modals
import { PaymentModal } from './components/modals/PaymentModal';
import { UpiPinModal } from './components/modals/UpiPinModal';
import { PaymentSuccessModal } from './components/modals/PaymentSuccessModal';
import { RiskGateModal } from './components/modals/RiskGateModal';
import { ScratchCardModal } from './components/modals/ScratchCardModal';
import { QrModal } from './components/modals/QrModal';
import { CheckBalanceModal } from './components/modals/CheckBalanceModal';
import { ReceiptModal } from './components/modals/ReceiptModal';
import { ProfileSettingsModal } from './components/profile/ProfileSettingsModal';
import { NotificationModal } from './components/common/NotificationModal';

import { ArrowRight, History, ArrowUpRight, ArrowDownLeft } from 'lucide-react';

const MainContent = () => {
  const { activeTab, setActiveTab, transactions, setReceiptModal, user } = useApp();
  const [searchQuery, setSearchQuery] = useState('');

  const recentTransactions = transactions.slice(0, 4);

  return (
    <DeviceFrame>
      <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col font-sans transition-colors duration-200">
        {/* Global Navigation Header */}
        <Header searchQuery={searchQuery} setSearchQuery={setSearchQuery} />

        {/* Dynamic Tab Body */}
        <main className="flex-1 w-full max-w-4xl mx-auto px-4 py-4 space-y-6">
          {activeTab === 'home' && (
            <div className="space-y-6 animate-fade-in">
              {/* Primary Balance Glance */}
              <BalanceCard />

              {/* 8-Grid Quick Actions */}
              <QuickActions />

              {/* Contacts / People to Pay */}
              <PeopleSection searchQuery={searchQuery} />

              {/* Businesses / Merchant Partners */}
              <BusinessesSection />

              {/* Rewards & Scratch Cards */}
              <RewardsPreview />

              {/* Recent Activity Quick Stream */}
              <section className="py-2">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-base font-bold text-white tracking-tight font-heading">
                    Recent Activity
                  </h2>
                  <button
                    onClick={() => setActiveTab('history')}
                    className="text-xs text-blue-400 hover:text-blue-300 font-semibold flex items-center gap-1 cursor-pointer"
                  >
                    <span>View All</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="space-y-2">
                  {recentTransactions.map((tx) => {
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
                              {tx.timestamp} • {tx.category}
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
                  })}
                </div>
              </section>
            </div>
          )}

          {activeTab === 'bills' && <BillsHub />}
          {activeTab === 'split' && <SplitExpenses />}
          {activeTab === 'cards' && <CardsManager />}
          {activeTab === 'history' && <TransactionHistory />}
        </main>

        {/* Bottom Floating Navigation */}
        <Navbar />

        {/* Global Modals */}
        <PaymentModal />
        <UpiPinModal />
        <PaymentSuccessModal />
        <RiskGateModal />
        <ScratchCardModal />
        <QrModal />
        <CheckBalanceModal />
        <ReceiptModal />
        <ProfileSettingsModal />
        <NotificationModal />
      </div>
    </DeviceFrame>
  );
};

export default function App() {
  return (
    <AppProvider>
      <MainContent />
    </AppProvider>
  );
}
