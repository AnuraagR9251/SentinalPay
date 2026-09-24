import React, { createContext, useContext, useState, useEffect } from 'react';
import confetti from 'canvas-confetti';
import { sound } from '../utils/audio';
import {
  INITIAL_USER,
  INITIAL_BANKS,
  INITIAL_CARDS,
  INITIAL_CONTACTS,
  INITIAL_MERCHANTS,
  INITIAL_BILLS,
  INITIAL_REWARDS,
  INITIAL_TRANSACTIONS,
  INITIAL_SPLIT_GROUPS
} from '../data/mockData';

const AppContext = createContext();

const STORAGE_KEY = 'senitenial_pay_v1';

export const AppProvider = ({ children }) => {
  // Load initial state from LocalStorage if available
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_user`);
    return saved ? JSON.parse(saved) : INITIAL_USER;
  });

  const [banks, setBanks] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_banks`);
    return saved ? JSON.parse(saved) : INITIAL_BANKS;
  });

  const [cards, setCards] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_cards`);
    return saved ? JSON.parse(saved) : INITIAL_CARDS;
  });

  const [contacts, setContacts] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_contacts`);
    return saved ? JSON.parse(saved) : INITIAL_CONTACTS;
  });

  const [merchants] = useState(INITIAL_MERCHANTS);

  const [bills, setBills] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_bills`);
    return saved ? JSON.parse(saved) : INITIAL_BILLS;
  });

  const [rewards, setRewards] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_rewards`);
    return saved ? JSON.parse(saved) : INITIAL_REWARDS;
  });

  const [transactions, setTransactions] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_transactions`);
    return saved ? JSON.parse(saved) : INITIAL_TRANSACTIONS;
  });

  const [splits, setSplits] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_splits`);
    return saved ? JSON.parse(saved) : INITIAL_SPLIT_GROUPS;
  });

  const [notifications, setNotifications] = useState([
    {
      id: "notif-1",
      title: "Security Shield Update",
      message: "Sentinel AI biometric security protection active.",
      time: "10m ago",
      unread: true
    },
    {
      id: "notif-2",
      title: "Reward Available!",
      message: "You have 2 unscratched cards waiting to be unlocked.",
      time: "1h ago",
      unread: true
    },
    {
      id: "notif-3",
      title: "Electricity Bill Due",
      message: "Tata Power bill of ₹1,840 is due on 28th Sep.",
      time: "4h ago",
      unread: false
    }
  ]);

  // App settings & view modes
  const [theme, setTheme] = useState('dark');
  const [deviceFrame, setDeviceFrame] = useState(false); // false = responsive desktop/mobile, true = phone frame
  const [activeTab, setActiveTab] = useState('home'); // home, bills, split, cards, history
  const [soundEnabled, setSoundEnabled] = useState(true);

  // Modals state
  const [paymentModal, setPaymentModal] = useState({
    isOpen: false,
    recipient: null,
    prefillAmount: '',
    prefillCategory: 'Payment',
    defaultMethod: null
  });

  const [upiPinModal, setUpiPinModal] = useState({
    isOpen: false,
    onComplete: null,
    amount: 0,
    recipientName: '',
    purpose: ''
  });

  const [paymentSuccessModal, setPaymentSuccessModal] = useState({
    isOpen: false,
    transaction: null,
    scratchReward: null
  });

  const [qrModal, setQrModal] = useState({
    isOpen: false,
    tab: 'scan' // 'scan' or 'myqr'
  });

  const [scratchCardModal, setScratchCardModal] = useState({
    isOpen: false,
    reward: null
  });

  const [checkBalanceModal, setCheckBalanceModal] = useState({
    isOpen: false,
    bank: null
  });

  const [receiptModal, setReceiptModal] = useState({
    isOpen: false,
    transaction: null
  });

  const [splitModal, setSplitModal] = useState({ isOpen: false });
  const [profileModal, setProfileModal] = useState({ isOpen: false });
  const [notificationModal, setNotificationModal] = useState({ isOpen: false });
  const [addBankModal, setAddBankModal] = useState({ isOpen: false });
  const [riskGateModal, setRiskGateModal] = useState({
    isOpen: false,
    phase: 'idle',
    riskTier: null,
    riskScore: null,
    payeeName: '',
    amount: 0
  });

  const SCORE_API = import.meta.env.VITE_SCORE_API_URL || 'http://localhost:8000';
  const DEMO_LOCATION = { lat: 18.5204, lon: 73.8567 };

  // Sync to local storage
  useEffect(() => {
    localStorage.setItem(`${STORAGE_KEY}_user`, JSON.stringify(user));
  }, [user]);

  useEffect(() => {
    localStorage.setItem(`${STORAGE_KEY}_banks`, JSON.stringify(banks));
  }, [banks]);

  useEffect(() => {
    localStorage.setItem(`${STORAGE_KEY}_cards`, JSON.stringify(cards));
  }, [cards]);

  useEffect(() => {
    localStorage.setItem(`${STORAGE_KEY}_contacts`, JSON.stringify(contacts));
  }, [contacts]);

  useEffect(() => {
    localStorage.setItem(`${STORAGE_KEY}_bills`, JSON.stringify(bills));
  }, [bills]);

  useEffect(() => {
    localStorage.setItem(`${STORAGE_KEY}_rewards`, JSON.stringify(rewards));
  }, [rewards]);

  useEffect(() => {
    localStorage.setItem(`${STORAGE_KEY}_transactions`, JSON.stringify(transactions));
  }, [transactions]);

  useEffect(() => {
    localStorage.setItem(`${STORAGE_KEY}_splits`, JSON.stringify(splits));
  }, [splits]);

  // Sound toggle effect
  useEffect(() => {
    sound.toggleSound(soundEnabled);
  }, [soundEnabled]);

  // Handle dark / light class on body
  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  // Triggers Payment Flow with PIN verification
  const startPaymentFlow = (recipient, prefillAmount = '', prefillCategory = 'Transfer') => {
    sound.playTap();
    setPaymentModal({
      isOpen: true,
      recipient,
      prefillAmount: prefillAmount ? String(prefillAmount) : '',
      prefillCategory,
      defaultMethod: banks[0]?.bankName || "Senitenial Wallet"
    });
  };

  // Execute transaction after PIN approval
  const executePayment = ({ recipient, amount, category, method, note }) => {
    const numAmount = parseFloat(amount);
    if (isNaN(numAmount) || numAmount <= 0) return;

    // Deduct balance from selected bank or wallet
    if (method.includes("Wallet")) {
      setUser(prev => ({
        ...prev,
        walletBalance: Math.max(0, prev.walletBalance - numAmount)
      }));
    } else {
      setBanks(prev => prev.map(bank => {
        if (method.includes(bank.bankName) || bank.isPrimary) {
          return { ...bank, balance: Math.max(0, bank.balance - numAmount) };
        }
        return bank;
      }));
    }

    // Generate unique UTR
    const utr = `SENT${Math.floor(100000000000 + Math.random() * 900000000000)}`;
    const txId = `tx-${Date.now()}`;

    const newTx = {
      id: txId,
      title: recipient.name || recipient.billerName || "Merchant Payment",
      upiId: recipient.upiId || "upi@senitenial",
      type: "debit",
      amount: numAmount,
      category: category || "Payment",
      timestamp: "Just now",
      status: "Success",
      method: method || "SBI •••• 4821",
      utr,
      note: note || "Paid via Senitenial Pay"
    };

    setTransactions(prev => [newTx, ...prev]);

    // Random scratch card reward generation for transactions over ₹50
    let awardedReward = null;
    if (numAmount >= 50 && Math.random() > 0.25) {
      const rewardId = `reward-${Date.now()}`;
      const rewardAmt = Math.floor(Math.random() * 85) + 15;
      awardedReward = {
        id: rewardId,
        type: "cashback",
        title: "Cashback Reward",
        amount: rewardAmt,
        description: `Won on payment to ${recipient.name || "merchant"}`,
        isScratched: false,
        expiryDate: "Valid for 7 days",
        code: `SENTINEL-WIN-${Math.floor(1000 + Math.random() * 9000)}`
      };
      setRewards(prev => [awardedReward, ...prev]);
    }

    // Play chime sound
    sound.playSuccessChime();

    // Trigger full confetti
    try {
      confetti({
        particleCount: 80,
        spread: 70,
        origin: { y: 0.6 },
        colors: ['#3b82f6', '#10b981', '#f59e0b', '#6366f1']
      });
    } catch {
      // ignore
    }

    // Open success modal
    setPaymentSuccessModal({
      isOpen: true,
      transaction: newTx,
      scratchReward: awardedReward
    });
  };

  const scoreAndExecutePayment = async ({ recipient, amount, category, method, note }) => {
    const numAmount = parseFloat(amount);
    if (isNaN(numAmount) || numAmount <= 0) return;

    const transactionId = `tx-${Date.now()}`;
    const payee = recipient.upiId || 'upi@senitenial';
    const known = new Set([
      ...contacts.map((c) => c.upiId),
      ...transactions.map((t) => t.upiId)
    ]);

    setRiskGateModal({
      isOpen: true,
      phase: 'scanning',
      riskTier: null,
      riskScore: null,
      payeeName: recipient.name || recipient.billerName || 'payee',
      amount: numAmount
    });

    try {
      const response = await fetch(`${SCORE_API}/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          transaction_id: transactionId,
          amount: numAmount,
          payee_vpa: payee,
          user_id: user.upiId,
          timestamp: new Date().toISOString(),
          payer_location: DEMO_LOCATION,
          is_new_payee: !known.has(payee)
        })
      });
      const data = await response.json();
      console.log('[SentinalPay /score]', data);
      if (!response.ok) {
        setRiskGateModal((prev) => ({ ...prev, phase: 'error' }));
        return;
      }
      const tier = data.risk_tier;
      if (tier === 'ALLOW') {
        setRiskGateModal({
          isOpen: false,
          phase: 'idle',
          riskTier: null,
          riskScore: null,
          payeeName: '',
          amount: 0
        });
        executePayment({ recipient, amount: numAmount, category, method, note });
        return;
      }
      if (tier === 'STEP_UP') {
        setRiskGateModal({
          isOpen: false,
          phase: 'idle',
          riskTier: null,
          riskScore: null,
          payeeName: '',
          amount: 0
        });
        setUpiPinModal({
          isOpen: true,
          stepUp: true,
          amount: numAmount,
          recipientName: recipient.name || recipient.billerName || 'Merchant',
          purpose: 'Sentinel step-up',
          onComplete: () => {
            executePayment({ recipient, amount: numAmount, category, method, note });
          }
        });
        return;
      }
      if (tier === 'HOLD') {
        setRiskGateModal((prev) => ({
          ...prev,
          phase: 'hold',
          riskTier: tier,
          riskScore: data.risk_score
        }));
        return;
      }
      setRiskGateModal((prev) => ({
        ...prev,
        phase: 'block',
        riskTier: tier,
        riskScore: data.risk_score
      }));
    } catch (err) {
      console.log('[SentinalPay /score] error', err);
      setRiskGateModal((prev) => ({ ...prev, phase: 'error' }));
    }
  };

  // Claim scratch card and add cashback to user's wallet
  const claimScratchCard = (rewardId, amount) => {
    setRewards(prev => prev.map(r => {
      if (r.id === rewardId) {
        return { ...r, isScratched: true, scratchedAt: "Just now" };
      }
      return r;
    }));

    if (amount > 0) {
      setUser(prev => ({
        ...prev,
        walletBalance: prev.walletBalance + amount
      }));

      // Add a credit reward transaction
      const rewardTx = {
        id: `tx-reward-${Date.now()}`,
        title: "Senitenial Cashback Reward",
        upiId: "rewards@senitenial",
        type: "credit",
        amount,
        category: "Rewards",
        timestamp: "Just now",
        status: "Success",
        method: "Senitenial Wallet",
        utr: `SENT${Math.floor(100000000000 + Math.random() * 900000000000)}`,
        note: "Cashback credited to wallet"
      };
      setTransactions(prev => [rewardTx, ...prev]);
    }

    sound.playSuccessChime();
    confetti({
      particleCount: 50,
      spread: 60,
      origin: { y: 0.5 }
    });
  };

  // Pay Utility Bill
  const payBill = (billId) => {
    const targetBill = bills.find(b => b.id === billId);
    if (!targetBill) return;

    startPaymentFlow(
      {
        name: targetBill.billerName,
        upiId: `${targetBill.category.toLowerCase()}@billpay`,
        avatar: null,
        isBill: true
      },
      targetBill.amountDue,
      `Utility Bill - ${targetBill.category}`
    );

    // After payment modal closes and succeeds, update bill status
    setBills(prev => prev.map(b => b.id === billId ? { ...b, status: "Paid" } : b));
  };

  // Add bank account
  const addBank = (bankName) => {
    const newBank = {
      id: `bank-${Date.now()}`,
      bankName,
      accountNumber: `•••• ${Math.floor(1000 + Math.random() * 9000)}`,
      accountType: "Savings Account",
      balance: Math.floor(Math.random() * 45000) + 15000,
      ifsc: `${bankName.substring(0, 4).toUpperCase()}0001892`,
      isPrimary: false,
      color: "from-blue-600 to-indigo-800",
      logoText: bankName.substring(0, 4).toUpperCase()
    };
    setBanks(prev => [...prev, newBank]);
    sound.playTap();
  };

  // Toggle freeze on card
  const toggleCardFreeze = (cardId) => {
    sound.playTap();
    setCards(prev => prev.map(c => c.id === cardId ? { ...c, isFrozen: !c.isFrozen } : c));
  };

  // Add new Split group
  const addSplitGroup = (newSplit) => {
    sound.playTap();
    setSplits(prev => [newSplit, ...prev]);
  };

  // Reset demo data
  const resetToDemo = () => {
    localStorage.clear();
    setUser(INITIAL_USER);
    setBanks(INITIAL_BANKS);
    setCards(INITIAL_CARDS);
    setContacts(INITIAL_CONTACTS);
    setBills(INITIAL_BILLS);
    setRewards(INITIAL_REWARDS);
    setTransactions(INITIAL_TRANSACTIONS);
    setSplits(INITIAL_SPLIT_GROUPS);
    sound.playSuccessChime();
  };

  return (
    <AppContext.Provider
      value={{
        user,
        setUser,
        banks,
        cards,
        contacts,
        merchants,
        bills,
        rewards,
        transactions,
        splits,
        notifications,
        setNotifications,
        theme,
        setTheme,
        deviceFrame,
        setDeviceFrame,
        activeTab,
        setActiveTab,
        soundEnabled,
        setSoundEnabled,
        paymentModal,
        setPaymentModal,
        upiPinModal,
        setUpiPinModal,
        paymentSuccessModal,
        setPaymentSuccessModal,
        qrModal,
        setQrModal,
        scratchCardModal,
        setScratchCardModal,
        checkBalanceModal,
        setCheckBalanceModal,
        receiptModal,
        setReceiptModal,
        splitModal,
        setSplitModal,
        profileModal,
        setProfileModal,
        notificationModal,
        setNotificationModal,
        addBankModal,
        setAddBankModal,
        riskGateModal,
        setRiskGateModal,
        startPaymentFlow,
        executePayment,
        scoreAndExecutePayment,
        claimScratchCard,
        payBill,
        addBank,
        toggleCardFreeze,
        addSplitGroup,
        resetToDemo
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useApp must be used within an AppProvider');
  }
  return context;
};
