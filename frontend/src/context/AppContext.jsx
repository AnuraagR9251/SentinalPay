import React, { createContext, useContext, useState, useEffect, useRef } from 'react';
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
  INITIAL_SPLIT_GROUPS,
  DEMO_PROFILES
} from '../data/mockData';
import { loginViaGraphql, scoreViaGraphql, verifyPinViaGraphql } from '../api/graphql';
import { mayMutateBalance } from '../api/holdAssessment';
import { attemptKey, claimAttempt, releaseAttempt, withinUpiLimit } from '../api/paymentAttempt';
import { openRazorpayCheckout, rupeesToPaise } from '../api/razorpayCheckout';
import { SECONDARY_COPY, paymentGate } from '../api/scoreDisplay';
import { applyClientLogout, demoResetImpliesSuccess, logoutViaRest, scoreApiRoot } from '../api/session';
import { runLabScenario as executeLabScenario } from '../lab/runScenario';

const AppContext = createContext();

const STORAGE_KEY = 'senitenial_pay_v1';
const cloneSeed = (value) => JSON.parse(JSON.stringify(value));

export const AppProvider = ({ children }) => {
  // Load initial state from LocalStorage if available
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_user`);
    return saved ? JSON.parse(saved) : cloneSeed(INITIAL_USER);
  });

  const [banks, setBanks] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_banks`);
    return saved ? JSON.parse(saved) : cloneSeed(INITIAL_BANKS);
  });

  const [cards, setCards] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_cards`);
    return saved ? JSON.parse(saved) : cloneSeed(INITIAL_CARDS);
  });

  const [contacts, setContacts] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_contacts`);
    return saved ? JSON.parse(saved) : cloneSeed(INITIAL_CONTACTS);
  });

  const [merchants] = useState(() => cloneSeed(INITIAL_MERCHANTS));

  const [bills, setBills] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_bills`);
    return saved ? JSON.parse(saved) : cloneSeed(INITIAL_BILLS);
  });

  const [rewards, setRewards] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_rewards`);
    return saved ? JSON.parse(saved) : cloneSeed(INITIAL_REWARDS);
  });

  const [transactions, setTransactions] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_transactions`);
    return saved ? JSON.parse(saved) : cloneSeed(INITIAL_TRANSACTIONS);
  });

  const [splits, setSplits] = useState(() => {
    const saved = localStorage.getItem(`${STORAGE_KEY}_splits`);
    return saved ? JSON.parse(saved) : cloneSeed(INITIAL_SPLIT_GROUPS);
  });

  const [notifications, setNotifications] = useState([
    {
      id: "notif-1",
      title: "Sandbox notice",
      message: "Fingerprint and Face ID in this app are simulated. SentinalPay is not a payment processor.",
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

  const [sessionToken, setSessionToken] = useState(() => localStorage.getItem(`${STORAGE_KEY}_token`) || '');
  const [authError, setAuthError] = useState('');
  const [lastScore, setLastScore] = useState(null);
  const paymentAttempts = useRef({});
  const [lastLab, setLastLab] = useState(null);
  const requireLogin = import.meta.env.VITE_REQUIRE_LOGIN === '1';

  const payerLocation = () => {
    const loc = user.location || DEMO_PROFILES.find((item) => item.upiId === user.upiId)?.location;
    if (loc && loc.lat != null && loc.lon != null) {
      return { lat: loc.lat, lon: loc.lon };
    }
    return null;
  };

  const authHeaders = () => ({
    'Content-Type': 'application/json',
    ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {})
  });

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

  const claimPaymentAttempt = ({ userId, amount, merchantId, deviceId, latitude, longitude }) => {
    const key = attemptKey({ userId, amount, merchantId, deviceId, latitude, longitude });
    return claimAttempt(paymentAttempts.current, key, Date.now());
  };

  const finishPaymentAttempt = ({ userId, amount, merchantId, deviceId, latitude, longitude }) => {
    releaseAttempt(paymentAttempts.current, attemptKey({ userId, amount, merchantId, deviceId, latitude, longitude }));
  };

  // Execute transaction after PIN approval
  const executePayment = ({ recipient, amount, category, method, note, transactionId, score, razorpay }) => {
    const numAmount = parseFloat(amount);
    if (isNaN(numAmount) || numAmount <= 0) return;
    const loc = payerLocation() || {};
    finishPaymentAttempt({
      userId: user.upiId,
      amount: numAmount,
      merchantId: recipient.upiId || 'upi@senitenial',
      deviceId: user.deviceId || '',
      latitude: loc.lat,
      longitude: loc.lon,
    });

    if ((method || "").includes("Wallet")) {
      setUser(prev => ({
        ...prev,
        walletBalance: Math.max(0, prev.walletBalance - numAmount)
      }));
    } else {
      setBanks(prev => prev.map(bank => {
        if ((method || "").includes(bank.bankName) || bank.isPrimary) {
          return { ...bank, balance: Math.max(0, bank.balance - numAmount) };
        }
        return bank;
      }));
    }

    const txId = transactionId || `sandbox-${Date.now()}`;
    const utr = `DEMO-${txId}`;
    const decision = score?.canonical_decision || null;

    const newTx = {
      id: txId,
      title: recipient.name || recipient.billerName || "Merchant Payment",
      upiId: recipient.upiId || "upi@senitenial",
      type: "debit",
      amount: numAmount,
      category: category || "Payment",
      timestamp: "Just now",
      status: razorpay ? 'Successful' : decision === 'REVIEW' ? 'Review' : 'Sandbox',
      method: method || "SBI •••• 4821",
      utr,
      note: note || "Sandbox ledger only — not a bank settlement",
      decision,
      riskScore: score?.canonical_risk_score ?? null,
      razorpay: Boolean(razorpay),
    };

    setTransactions(prev => [newTx, ...prev]);

    if (recipient?.billId) {
      setBills((prev) => prev.map((bill) => (
        bill.id === recipient.billId ? { ...bill, status: "Paid" } : bill
      )));
    }

    // Random scratch card reward generation for transactions over ₹50
    let awardedReward = null;
    if (numAmount >= 50 && Math.random() > 0.25) {
      const rewardId = `reward-${Date.now()}`;
      const rewardAmt = Math.floor(Math.random() * 85) + 15;
      awardedReward = {
        id: rewardId,
        type: "cashback",
        title: "Demo cashback (sandbox)",
        amount: rewardAmt,
        description: `Generated locally on sandbox debit to ${recipient.name || "merchant"}`,
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

  const continueHeldCheckout = async ({ recipient, amount, category, note, transactionId, timestamp }) => {
    const paise = rupeesToPaise(amount);
    const key = import.meta.env.VITE_RAZORPAY_KEY_ID;
    if (!paise || !key) {
      setRiskGateModal((prev) => ({
        ...prev,
        phase: 'error',
        message: 'Payment was not authorized.',
      }));
      return;
    }
    try {
      const loc = payerLocation() || {};
      const created = await fetch(`${scoreApiRoot().replace(/\/$/, '')}/api/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          amount: paise,
          currency: 'INR',
          transaction_id: transactionId,
          user_id: user.upiId,
          merchant_id: recipient.upiId || 'upi@senitenial',
          merchant_category: category || 'p2p',
          device_id: user.deviceId || null,
          timestamp: timestamp || new Date().toISOString(),
          latitude: loc.lat,
          longitude: loc.lon,
          receipt: transactionId.slice(0, 40),
        }),
      });
      const body = await created.json().catch(() => ({}));
      if (!created.ok || !body.order_id) {
        setRiskGateModal((prev) => ({
          ...prev,
          phase: 'error',
          message: 'Payment was not authorized.',
        }));
        return;
      }
      setRiskGateModal({ isOpen: false, phase: 'idle', payeeName: '', amount: 0 });
      openRazorpayCheckout({
        key,
        order: body,
        onSuccess: async (response) => {
          const verified = await fetch(`${scoreApiRoot().replace(/\/$/, '')}/api/verify-payment`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
              transaction_id: transactionId,
            }),
          });
          const verdict = await verified.json().catch(() => ({}));
          if (verified.ok && mayMutateBalance(verdict.settled)) {
            executePayment({
              recipient,
              amount,
              category,
              method: 'Razorpay',
              note: note || 'Sandbox ledger — not a bank settlement',
              transactionId,
              score: { canonical_decision: body.decision, canonical_risk_score: body.risk_score },
              razorpay: true,
            });
            return;
          }
          setRiskGateModal({
            isOpen: true,
            phase: 'error',
            payeeName: recipient.name || 'payee',
            amount,
            message: 'Payment is not settled. Sandbox balance was not changed.',
          });
        },
        onDismiss: () => setRiskGateModal({
          isOpen: true,
          phase: 'error',
          payeeName: recipient.name || 'payee',
          amount,
          message: 'Payment cancelled. Sandbox balance was not changed.',
        }),
        onFailed: () => setRiskGateModal({
          isOpen: true,
          phase: 'block',
          payeeName: recipient.name || 'payee',
          amount,
          message: 'Payment failed. Sandbox balance was not changed.',
        }),
      });
    } catch {
      setRiskGateModal((prev) => ({
        ...prev,
        phase: 'error',
        message: 'Payment was not authorized.',
      }));
    }
  };

  const scoreAndExecutePayment = async ({ recipient, amount, category, method, note, onCleared }) => {
    const numAmount = parseFloat(amount);
    if (!withinUpiLimit(numAmount)) return;

    const payee = recipient.upiId || 'upi@senitenial';
    const loc = payerLocation() || {};
    const attempt = claimPaymentAttempt({
      userId: user.upiId,
      amount: numAmount,
      merchantId: payee,
      deviceId: user.deviceId || '',
      latitude: loc.lat,
      longitude: loc.lon,
    });
    const transactionId = attempt.transactionId;
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
      const data = await scoreViaGraphql(
        {
          transactionId,
          amount: numAmount,
          payeeVpa: payee,
          userId: user.upiId,
          timestamp: attempt.timestamp,
          payerLocation: loc.lat == null ? null : loc,
          deviceId: user.deviceId || null,
          isNewPayee: !known.has(payee),
          purpose: category || note || 'p2p_transfer'
        },
        authHeaders()
      );
      console.log('[SentinalPay /graphql score]', data);
      setLastScore(data);
      const gate = paymentGate(data);
      const settle = () => {
        setRiskGateModal({
          isOpen: false,
          phase: 'idle',
          riskTier: null,
          riskScore: null,
          payeeName: '',
          amount: 0
        });
        if (onCleared) onCleared({ transactionId, score: data });
        else executePayment({ recipient, amount: numAmount, category, method, note, transactionId, score: data });
      };
      if (gate === 'pay') {
        settle();
        return;
      }
      if (gate === 'otp') {
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
          review: false,
          amount: numAmount,
          recipientName: recipient.name || recipient.billerName || 'Merchant',
          purpose: 'Step-up check',
          onComplete: settle
        });
        return;
      }
      if (gate === 'hold') {
        setRiskGateModal((prev) => ({
          ...prev,
          phase: 'hold',
          transactionId,
          deadline: new Date(Date.now() + 15000).toISOString(),
          riskTier: data.action || 'HOLD',
          riskScore: data.canonical_risk_score,
          canonicalRiskScore: data.canonical_risk_score,
          pXgb: data.P_xgb,
          mlCalibrated: data.ml_calibrated_for_upi,
          canonicalDecision: data.canonical_decision,
          message: SECONDARY_COPY.PENDING,
          reasons: (data.explanation && data.explanation.triggered_rules) || data.reason_codes || [],
          onContinue: settle
        }));
        return;
      }
      setRiskGateModal((prev) => ({
        ...prev,
        phase: 'block',
        riskTier: data.risk_tier,
        riskScore: data.canonical_risk_score,
        canonicalRiskScore: data.canonical_risk_score,
        pXgb: data.P_xgb,
        mlCalibrated: data.ml_calibrated_for_upi,
        canonicalDecision: data.canonical_decision,
        reasons: (data.explanation && data.explanation.triggered_rules) || data.reason_codes || [],
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
        status: "Sandbox",
        method: "Senitenial Wallet",
        utr: `DEMO-reward-${rewardId}`,
        note: "Generated demo cashback — not a bank credit"
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
        isBill: true,
        billId: targetBill.id
      },
      targetBill.amountDue,
      `Utility Bill - ${targetBill.category}`
    );
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

  const switchDemoUser = (profileId) => {
    const profile = DEMO_PROFILES.find((item) => item.id === profileId);
    if (!profile) return;
    setUser((prev) => ({
      ...prev,
      name: profile.name,
      upiId: profile.upiId,
      city: profile.city,
      location: profile.location,
      deviceId: profile.deviceId,
      walletBalance: profile.walletBalance
    }));
  };

  const loginWithPassword = async (userId, password) => {
    setAuthError('');
    try {
      const data = await loginViaGraphql(userId, password);
      setSessionToken(data.token);
      localStorage.setItem(`${STORAGE_KEY}_token`, data.token);
      const profile = DEMO_PROFILES.find((item) => item.upiId === userId);
      if (profile) switchDemoUser(profile.id);
      else setUser((prev) => ({ ...prev, upiId: userId }));
      return true;
    } catch (err) {
      setAuthError(err.message || 'Login failed');
      return false;
    }
  };

  const verifyPin = async (pin, challengeId = null) => {
    try {
      return await verifyPinViaGraphql(pin, authHeaders(), challengeId);
    } catch {
      return { ok: false, error: 'invalid_pin' };
    }
  };

  const runLabScenario = async (id, extras = {}) => {
    const out = await executeLabScenario(id, {
      headers: authHeaders(),
      sessionUser: user.upiId,
      requireLogin,
      threshold: extras.threshold,
    });
    setLastLab(out);
    setLastScore(out.candidate);
    return out;
  };

  const logout = async () => {
    const token = sessionToken;
    const result = token ? await logoutViaRest(token) : { revoked: true, error: null };
    const next = applyClientLogout(localStorage, STORAGE_KEY, result);
    setSessionToken(next.sessionToken);
    setLastScore(next.lastScore);
    setLastLab(null);
    setAuthError(next.authError);
    return next;
  };

  const resetToDemo = async () => {
    const next = await logout();
    localStorage.clear();
    setUser(cloneSeed(INITIAL_USER));
    setBanks(cloneSeed(INITIAL_BANKS));
    setCards(cloneSeed(INITIAL_CARDS));
    setContacts(cloneSeed(INITIAL_CONTACTS));
    setBills(cloneSeed(INITIAL_BILLS));
    setRewards(cloneSeed(INITIAL_REWARDS));
    setTransactions(cloneSeed(INITIAL_TRANSACTIONS));
    setSplits(cloneSeed(INITIAL_SPLIT_GROUPS));
    setSessionToken('');
    setLastScore(null);
    setLastLab(null);
    setAuthError(next.authError);
    if (demoResetImpliesSuccess(next)) {
      sound.playSuccessChime();
    }
    return next;
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
        claimPaymentAttempt,
        scoreAndExecutePayment,
        claimScratchCard,
        payBill,
        addBank,
        toggleCardFreeze,
        addSplitGroup,
        resetToDemo,
        logout,
        sessionToken,
        authError,
        lastScore,
        setLastScore,
        lastLab,
        requireLogin,
        switchDemoUser,
        loginWithPassword,
        runLabScenario,
        verifyPin
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
