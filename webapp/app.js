/**
 * SPeCTRUM Attendance Telegram Mini App (TMA) Dashboard
 * Client-side Controller & Lifecycle Management
 */

(function () {
  'use strict';

  // --------------------------------------------------------------------------
  // Default Course & Schedule Configurations
  // --------------------------------------------------------------------------
  const DEFAULT_COURSES = [
    {
      course_id: "1121957",
      course_name: "WIA2006 Lecture (DK1)",
      code: "WIA2006",
      component: "Lecture DK1",
      schedule: "Thursday 16:00 - 18:00",
      day: "Thursday",
      taken_sessions: 1,
      points_achieved: 2,
      points_total: 2,
      attendance_rate: 100.0,
      below_threshold: false,
      sessions: [
        {
          date: "Thu 22 Oct 2026 4PM - 6PM",
          day: "Thursday",
          description: "Regular class session",
          status: "Present",
          points: "2 / 2",
          remarks: "Self-recorded"
        }
      ]
    },
    {
      course_id: "893285",
      course_name: "WIA2006 Tutorial (OCC3)",
      code: "WIA2006",
      component: "Tutorial OCC3",
      schedule: "Tuesday 10:00 - 12:00",
      day: "Tuesday",
      taken_sessions: 1,
      points_achieved: 2,
      points_total: 2,
      attendance_rate: 100.0,
      below_threshold: false,
      sessions: [
        {
          date: "Tue 20 Oct 2026 10AM - 12PM",
          day: "Tuesday",
          description: "Tutorial OCC3 session",
          status: "Present",
          points: "2 / 2",
          remarks: "Self-recorded"
        }
      ]
    },
    {
      course_id: "1120381",
      course_name: "SIF4001 Project (Daily Attendance)",
      code: "SIF4001",
      component: "Daily Project",
      schedule: "Mon - Fri 10:00 - 11:00",
      day: "Mon-Fri",
      taken_sessions: 5,
      points_achieved: 10,
      points_total: 10,
      attendance_rate: 100.0,
      below_threshold: false,
      sessions: [
        {
          date: "Fri 23 Oct 2026 10AM - 11AM",
          day: "Friday",
          description: "Daily Check-in",
          status: "Present",
          points: "2 / 2",
          remarks: "Self-recorded"
        }
      ]
    }
  ];

  const DAYS_OF_WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const SHORT_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  // --------------------------------------------------------------------------
  // Application State
  // --------------------------------------------------------------------------
  const state = {
    courses: [...DEFAULT_COURSES],
    authenticated: false,
    authConnectUrl: null,
    ssoPollTimer: null,
    lastChecked: null,
    isChecking: false,
    isSubmittingPassword: false,
    isLoggingIn: false,
    pendingSession: null
  };

  // --------------------------------------------------------------------------
  // Telegram WebApp SDK Integration
  // --------------------------------------------------------------------------
  function getTg() {
    return window.Telegram?.WebApp;
  }

  function initTelegram() {
    const tg = getTg();
    if (tg) {
      try {
        if (typeof tg.ready === 'function') {
          tg.ready();
          window._tgReadyExecuted = true;
        }
        if (typeof tg.expand === 'function') {
          tg.expand();
          window._tgExpandExecuted = true;
        }

        // Synchronize Telegram theme variables
        applyTelegramTheme();
        if (typeof tg.onEvent === 'function') {
          tg.onEvent('themeChanged', applyTelegramTheme);
        }

        // Populate user profile info from initDataUnsafe
        const user = tg.initDataUnsafe?.user;
        if (user) {
          const userNameEl = document.getElementById('userName');
          const userAvatarEl = document.getElementById('userAvatar');
          
          const fullName = [user.first_name, user.last_name].filter(Boolean).join(' ');
          if (userNameEl) {
            userNameEl.textContent = fullName || user.username || 'SPeCTRUM Student';
          }
          if (userAvatarEl) {
            const initials = ((user.first_name ? user.first_name[0] : '') + (user.last_name ? user.last_name[0] : '')).toUpperCase() || 'UM';
            userAvatarEl.textContent = initials;
          }
        }
      } catch (err) {
        console.warn('Telegram SDK initialization notice:', err);
      }
    } else {
      console.log('Running in browser fallback mode (outside Telegram WebApp)');
    }
  }

  function applyTelegramTheme() {
    const tg = getTg();
    if (!tg) return;
    const params = tg.themeParams;
    if (params) {
      const root = document.documentElement;
      if (params.bg_color) root.style.setProperty('--tg-theme-bg-color', params.bg_color);
      if (params.text_color) root.style.setProperty('--tg-theme-text-color', params.text_color);
      if (params.hint_color) root.style.setProperty('--tg-theme-hint-color', params.hint_color);
      if (params.link_color) root.style.setProperty('--tg-theme-link-color', params.link_color);
      if (params.button_color) root.style.setProperty('--tg-theme-button-color', params.button_color);
      if (params.button_text_color) root.style.setProperty('--tg-theme-button-text-color', params.button_text_color);
      if (params.secondary_bg_color) root.style.setProperty('--tg-theme-secondary-bg-color', params.secondary_bg_color);

      // Dark theme detection
      const isDark = tg.colorScheme === 'dark' || (params.bg_color && isColorDark(params.bg_color));
      document.body.classList.toggle('dark-theme', Boolean(isDark));
    }
  }

  function isColorDark(hex) {
    if (!hex || hex[0] !== '#') return false;
    const clean = hex.slice(1);
    const rgb = clean.length === 3
      ? clean.split('').map(c => parseInt(c + c, 16))
      : [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)];
    const brightness = (rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114) / 1000;
    return brightness < 128;
  }

  // Haptic Feedback Utilities
  function hapticImpact(style = 'light') {
    const tg = getTg();
    if (tg?.HapticFeedback) {
      try {
        tg.HapticFeedback.impactOccurred(style);
        window._lastHaptic = 'impact:' + style;
      } catch (e) { /* ignore */ }
    }
  }

  function hapticNotification(type = 'success') {
    const tg = getTg();
    if (tg?.HapticFeedback) {
      try {
        tg.HapticFeedback.notificationOccurred(type);
        window._lastHaptic = 'notification:' + type;
      } catch (e) { /* ignore */ }
    }
  }

  function hapticSelection() {
    const tg = getTg();
    if (tg?.HapticFeedback) {
      try {
        tg.HapticFeedback.selectionChanged();
        window._lastHaptic = 'selection';
      } catch (e) { /* ignore */ }
    }
  }

  // --------------------------------------------------------------------------
  // Toast Notifications
  // --------------------------------------------------------------------------
  function showToast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let iconSvg = '';
    if (type === 'success') {
      iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2.5" fill="none"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    } else if (type === 'warning') {
      iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2.5" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
    } else if (type === 'danger') {
      iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2.5" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>';
    } else {
      iconSvg = '<svg viewBox="0 0 24 24" width="18" height="18" stroke="currentColor" stroke-width="2.5" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
    }

    toast.innerHTML = `${iconSvg}<span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-10px)';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // --------------------------------------------------------------------------
  // Local Today Check-in Tracking
  // --------------------------------------------------------------------------
  function getTodayDateKey() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  function markCourseCheckedToday(courseId) {
    if (!courseId) return;
    try {
      const key = `spectrum_checked_${courseId}_${getTodayDateKey()}`;
      localStorage.setItem(key, new Date().toISOString());
    } catch (_) {}
    renderCourseCards();
  }

  function isCourseCheckedToday(courseId) {
    if (!courseId) return false;
    try {
      const key = `spectrum_checked_${courseId}_${getTodayDateKey()}`;
      return Boolean(localStorage.getItem(key));
    } catch (_) {
      return false;
    }
  }

  // --------------------------------------------------------------------------
  // Course Attendance Cards Rendering
  // --------------------------------------------------------------------------
  function renderCourseCards() {
    const container = document.getElementById('courseCardsContainer');
    if (!container) return;

    if (!state.courses || state.courses.length === 0) {
      container.innerHTML = '<div class="empty-state">No courses configured.</div>';
      return;
    }

    container.innerHTML = state.courses.map(course => {
      // Calculate or parse attendance rate
      let rate = course.attendance_rate;
      if (typeof rate === 'string') {
        rate = parseFloat(rate.replace('%', '')) || 0;
      } else if (typeof rate !== 'number') {
        rate = 0;
      }

      // 80% Barring Threshold Check
      const isBelowThreshold = course.below_threshold === true || rate < 80.0;
      const rateFormatted = rate.toFixed(1) + '%';
      
      const courseCode = course.code || extractCourseCode(course.course_name);
      const component = course.component || extractComponent(course.course_name);
      const pointsAchieved = course.points_achieved ?? course.points_earned ?? 0;
      const pointsTotal = course.points_total ?? 0;
      const takenSessions = course.taken_sessions ?? (course.sessions ? course.sessions.length : 0);
      const checkedToday = isCourseCheckedToday(course.course_id);

      const statusBadgeHtml = checkedToday
        ? `<span class="threshold-badge checked-today-badge" title="Attendance recorded for today's session">
             <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2.5" fill="none"><polyline points="20 6 9 17 4 12"></polyline></svg>
             Checked In Today
           </span>`
        : (isBelowThreshold
          ? `<span class="threshold-badge danger-badge" title="Universiti Malaya 80% Exam Barring Threshold">
               <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2.5" fill="none"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>
               &lt;80% Exam Barring Risk
             </span>`
          : `<span class="threshold-badge safe-badge" title="Attendance in Good Standing">
               <svg viewBox="0 0 24 24" width="13" height="13" stroke="currentColor" stroke-width="2.5" fill="none"><polyline points="20 6 9 17 4 12"></polyline></svg>
               &gt;=80% Safe Standing
             </span>`);

      return `
        <div class="course-card ${isBelowThreshold && !checkedToday ? 'below-threshold' : 'safe-threshold'}" data-course-id="${escapeHtml(course.course_id || '')}">
          <div class="course-card-top">
            <div class="course-meta">
              <div class="course-code-row">
                <span class="course-code-pill">${escapeHtml(courseCode)}</span>
                <span class="course-schedule-tag">
                  <svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                  ${escapeHtml(course.schedule || 'Regular Schedule')}
                </span>
              </div>
              <h3 class="course-name">${escapeHtml(course.course_name)}</h3>
            </div>
            <div class="course-rate-box">
              <span class="rate-percentage ${isBelowThreshold && !checkedToday ? 'danger' : 'safe'}">${rateFormatted}</span>
              ${statusBadgeHtml}
            </div>
          </div>

          <!-- Progress Bar with 80% Threshold Marker -->
          <div class="progress-container">
            <div class="progress-track" title="Attendance Progress: ${rateFormatted}">
              <div class="progress-marker-80" title="80% Minimum Requirement Marker"></div>
              <div class="progress-bar ${isBelowThreshold && !checkedToday ? 'danger' : 'safe'}" style="width: ${Math.min(100, Math.max(0, rate))}%"></div>
            </div>
          </div>

          <!-- Card Stats Footer -->
          <div class="course-card-footer">
            <div class="footer-stat">
              <span>Points:</span>
              <span class="stat-value">${pointsAchieved} / ${pointsTotal}</span>
            </div>
            <div class="footer-stat">
              <span>${checkedToday ? "Today's Status:" : "Recorded Sessions:"}</span>
              <span class="stat-value ${checkedToday ? 'text-success font-semibold' : ''}">${checkedToday ? "Present ✓" : takenSessions}</span>
            </div>
          </div>

          <!-- Direct 1-Tap Attendance Check Action -->
          <div class="course-card-actions">
            <a href="https://spectrum.um.edu.my/mod/attendance/view.php?id=${encodeURIComponent(course.course_id)}" 
               target="_blank" 
               class="btn-open-course ${checkedToday ? 'btn-recheck' : ''}" 
               onclick="handleDirectCourseOpen(event, 'https://spectrum.um.edu.my/mod/attendance/view.php?id=${encodeURIComponent(course.course_id)}', '${escapeHtml(course.course_id)}')">
              <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.5" fill="none"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
              <span>${checkedToday ? 'Re-check SPeCTRUM' : '1-Tap Check SPeCTRUM'}</span>
            </a>
          </div>
        </div>
      `;
    }).join('');
  }

  function extractCourseCode(name) {
    if (!name) return 'UM';
    const match = name.match(/^[A-Z]{3,4}\d{4}/i);
    return match ? match[0].toUpperCase() : 'COURSE';
  }

  function extractComponent(name) {
    if (!name) return 'Class';
    if (name.includes('Lecture')) return 'Lecture';
    if (name.includes('Tutorial')) return 'Tutorial';
    if (name.includes('Project')) return 'Project';
    return 'Class';
  }

  // --------------------------------------------------------------------------
  // Weekly Schedule Timeline (Monday to Sunday)
  // --------------------------------------------------------------------------
  function renderWeeklyTimeline() {
    const container = document.getElementById('weeklyTimeline');
    if (!container) return;

    const now = new Date();
    // getDay(): 0 is Sunday, 1 is Monday ... 6 is Saturday
    const currentDayIndex = now.getDay();
    const currentDayName = DAYS_OF_WEEK[currentDayIndex];

    // Standard week order: Monday through Sunday
    const weekDays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

    // Default scheduled classes mapping
    const defaultSchedule = {
      "Monday": [
        { course: "SIF4001 Daily Project", time: "10:00 - 11:00", type: "Daily Check-in", defaultStatus: "Scheduled" }
      ],
      "Tuesday": [
        { course: "WIA2006 Tutorial (OCC3)", time: "10:00 - 12:00", type: "Tutorial OCC3", defaultStatus: "Scheduled" },
        { course: "SIF4001 Daily Project", time: "10:00 - 11:00", type: "Daily Check-in", defaultStatus: "Scheduled" }
      ],
      "Wednesday": [
        { course: "SIF4001 Daily Project", time: "10:00 - 11:00", type: "Daily Check-in", defaultStatus: "Scheduled" }
      ],
      "Thursday": [
        { course: "SIF4001 Daily Project", time: "10:00 - 11:00", type: "Daily Check-in", defaultStatus: "Scheduled" },
        { course: "WIA2006 Lecture (DK1)", time: "16:00 - 18:00", type: "Lecture DK1", defaultStatus: "Scheduled" }
      ],
      "Friday": [
        { course: "SIF4001 Daily Project", time: "10:00 - 11:00", type: "Daily Check-in", defaultStatus: "Scheduled" }
      ],
      "Saturday": [],
      "Sunday": []
    };

    // Update today indicator text
    const todayIndicator = document.getElementById('todayIndicator');
    if (todayIndicator) {
      todayIndicator.textContent = `Today: ${currentDayName}`;
    }

    container.innerHTML = weekDays.map(dayName => {
      const isToday = (dayName === currentDayName);
      const classesForDay = defaultSchedule[dayName] || [];

      // Check if we have dynamic session records from API matching this day
      const sessionItemsHtml = classesForDay.length > 0
        ? classesForDay.map(cls => {
            // Find if any course in state has a session record for this day
            let statusText = cls.defaultStatus;
            let statusClass = "status-scheduled";

            // Cross-reference with courses sessions if present
            state.courses.forEach(c => {
              if (c.course_name && c.course_name.includes(cls.course.split(' ')[0])) {
                if (c.sessions && Array.isArray(c.sessions)) {
                  const match = c.sessions.find(s => s.day === dayName || (s.date && s.date.includes(dayName.slice(0, 3))));
                  if (match) {
                    statusText = match.status || 'Present';
                    if (statusText.toLowerCase().includes('present')) {
                      statusClass = "status-present";
                    } else if (statusText.toLowerCase().includes('open') || statusText.toLowerCase().includes('active')) {
                      statusClass = "status-open";
                    } else if (statusText.toLowerCase().includes('password')) {
                      statusClass = "status-password";
                    }
                  }
                }
              }
            });

            return `
              <div class="timeline-session-item">
                <div class="session-left">
                  <span class="session-title">${escapeHtml(cls.course)}</span>
                  <span class="session-time">
                    <svg viewBox="0 0 24 24" width="11" height="11" stroke="currentColor" stroke-width="2" fill="none"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                    ${cls.time} • ${cls.type}
                  </span>
                </div>
                <span class="session-status-badge ${statusClass}">
                  ${statusClass === 'status-present' ? '✓ ' : ''}${statusText}
                </span>
              </div>
            `;
          }).join('')
        : `<div class="weekend-quiet">No lectures or tutorials scheduled. Enjoy your weekend! 🎉</div>`;

      return `
        <div class="timeline-day-card ${isToday ? 'is-today' : ''}">
          <div class="day-header">
            <div class="day-title-group">
              <span class="day-name">${dayName}</span>
              ${isToday ? '<span class="today-pill">Today</span>' : ''}
            </div>
            <span class="day-count-badge">${classesForDay.length} class${classesForDay.length === 1 ? '' : 'es'}</span>
          </div>
          <div class="day-classes-list">
            ${sessionItemsHtml}
          </div>
        </div>
      `;
    }).join('');
  }

  // --------------------------------------------------------------------------
  // REST API Client
  // --------------------------------------------------------------------------
  async function fetchAttendanceStatus() {
    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) refreshBtn.classList.add('spinning');

    const connectionStatusEl = document.getElementById('connectionStatus');
    const authBadgeEl = document.getElementById('authBadge');
    const sessionStatusBadge = document.getElementById('sessionStatusBadge');

    if (window.location.protocol === 'file:') {
      console.log('Opened via file:// protocol; using offline fallback data.');
      if (connectionStatusEl) {
        connectionStatusEl.className = 'status-pill status-offline';
        connectionStatusEl.textContent = '● Local File Mode';
      }
      if (authBadgeEl) {
        authBadgeEl.className = 'auth-pill auth-inactive';
        authBadgeEl.textContent = 'Offline';
      }
      renderCourseCards();
      renderWeeklyTimeline();
      if (refreshBtn) refreshBtn.classList.remove('spinning');
      return;
    }

    try {
      const response = await fetch('/api/status', {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        cache: 'no-store'
      });

      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }

      const data = await response.json();

      // Update state with live data if non-empty, otherwise preserve pre-populated course baselines
      if (data.courses && Array.isArray(data.courses) && data.courses.length > 0) {
        const hasPopulatedStats = data.courses.some(c => (c.points_total || 0) > 0 || (c.sessions && c.sessions.length > 0));
        if (hasPopulatedStats) {
          state.courses = data.courses;
        }
      }
      state.authenticated = Boolean(data.authenticated);
      if (data.auth_connect_url) {
        state.authConnectUrl = data.auth_connect_url;
        const ssoBtn = document.getElementById('ssoConnectBtn');
        if (ssoBtn) ssoBtn.href = data.auth_connect_url;
      }

      // Update UI badges
      if (connectionStatusEl) {
        connectionStatusEl.className = 'status-pill status-online';
        connectionStatusEl.textContent = '● Connected';
      }

      if (authBadgeEl) {
        if (state.authenticated) {
          authBadgeEl.className = 'auth-pill auth-active';
          authBadgeEl.textContent = 'Authenticated';
        } else {
          authBadgeEl.className = 'auth-pill auth-active';
          authBadgeEl.textContent = 'Direct Mode';
        }
      }

      if (sessionStatusBadge) {
        if (state.authenticated) {
          sessionStatusBadge.className = 'session-badge badge-success';
          sessionStatusBadge.textContent = 'Session Active';
        } else {
          sessionStatusBadge.className = 'session-badge badge-success';
          sessionStatusBadge.textContent = 'Direct Mode Ready';
        }
      }

      // Render Cards and Timeline
      renderCourseCards();
      renderWeeklyTimeline();

    } catch (err) {
      console.warn('Could not fetch live status from /api/status:', err);
      if (connectionStatusEl) {
        connectionStatusEl.className = 'status-pill status-offline';
        connectionStatusEl.textContent = '● Standalone Mode';
      }
      if (authBadgeEl) {
        authBadgeEl.className = 'auth-pill auth-inactive';
        authBadgeEl.textContent = 'Offline';
      }
      // Render fallback data
      renderCourseCards();
      renderWeeklyTimeline();
    } finally {
      if (refreshBtn) refreshBtn.classList.remove('spinning');
    }
  }

  // Direct Course Open Handler (for Phone & Desktop Telegram Mini App)
  window.handleDirectCourseOpen = function(e, url, courseId) {
    if (e && typeof e.preventDefault === 'function') e.preventDefault();
    if (courseId) {
      markCourseCheckedToday(courseId);
    }
    const tg = getTg();
    if (tg && typeof tg.openLink === 'function') {
      try {
        tg.openLink(url);
        return;
      } catch (err) {
        console.warn('tg.openLink failed:', err);
      }
    }
    window.open(url, '_blank');
  };

  // 1-Tap Check Attendance Action
  async function triggerCheckAttendance() {
    if (state.isChecking) return;
    state.isChecking = true;
    hapticImpact('medium');

    const checkBtn = document.getElementById('checkAttendanceBtn');
    const spinner = document.getElementById('checkSpinner');
    const icon = document.getElementById('checkIcon');
    const btnText = document.getElementById('checkBtnText');
    const heroStatusText = document.getElementById('heroStatusText');
    const lastCheckedText = document.getElementById('lastCheckedText');

    if (checkBtn) checkBtn.disabled = true;
    if (spinner) spinner.classList.remove('hidden');
    if (icon) icon.classList.add('hidden');
    if (btnText) btnText.textContent = 'Opening SPeCTRUM...';
    if (heroStatusText) heroStatusText.textContent = 'Launching SPeCTRUM attendance...';

    // Determine target course based on current day & time
    const now = new Date();
    const day = now.getDay(); // 0 Sun, 1 Mon, 2 Tue, 3 Wed, 4 Thu, 5 Fri, 6 Sat
    let targetUrl = "https://spectrum.um.edu.my/mod/attendance/view.php?id=1120381"; // SIF4001 Daily Project default
    let courseName = "SIF4001 Daily Project";
    let targetCourseId = "1120381";

    if (day === 4 && now.getHours() >= 15) { // Thursday afternoon
      targetUrl = "https://spectrum.um.edu.my/mod/attendance/view.php?id=1121957";
      courseName = "WIA2006 Lecture (DK1)";
      targetCourseId = "1121957";
    } else if (day === 2 && now.getHours() >= 9 && now.getHours() < 13) { // Tuesday morning
      targetUrl = "https://spectrum.um.edu.my/mod/attendance/view.php?id=893285";
      courseName = "WIA2006 Tutorial (OCC3)";
      targetCourseId = "893285";
    }

    // Launch direct SPeCTRUM page on student phone
    handleDirectCourseOpen(null, targetUrl, targetCourseId);
    hapticNotification('success');
    showToast(`⚡ Opened ${courseName} on SPeCTRUM!`, 'success');

    // Also ping backend in background
    try {
      fetch('/api/check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({})
      }).catch(() => {});
    } catch (_) {}

    const nowFormatted = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (lastCheckedText) lastCheckedText.textContent = `Last launched: Today at ${nowFormatted}`;
    if (heroStatusText) heroStatusText.textContent = `Launched ${courseName}`;

    setTimeout(() => {
      state.isChecking = false;
      if (checkBtn) checkBtn.disabled = false;
      if (spinner) spinner.classList.add('hidden');
      if (icon) icon.classList.remove('hidden');
      if (btnText) btnText.textContent = 'Check Attendance Now';
    }, 2000);
  }

  // --------------------------------------------------------------------------
  // Password Submission Dialog
  // --------------------------------------------------------------------------
  function openPasswordModal(courseName) {
    const modal = document.getElementById('passwordModal');
    const courseDetails = document.getElementById('passwordSessionDetails');
    const input = document.getElementById('sessionPasswordInput');
    const feedback = document.getElementById('passwordModalFeedback');

    if (courseDetails) courseDetails.textContent = courseName || 'Active Class Session';
    if (input) {
      input.value = '';
      setTimeout(() => input.focus(), 150);
    }
    if (feedback) {
      feedback.className = 'modal-feedback hidden';
      feedback.textContent = '';
    }
    if (modal) {
      modal.classList.remove('hidden');
    }
  }

  function closePasswordModal() {
    const modal = document.getElementById('passwordModal');
    if (modal) modal.classList.add('hidden');
    hapticImpact('light');
  }

  async function submitPassword() {
    const input = document.getElementById('sessionPasswordInput');
    const feedback = document.getElementById('passwordModalFeedback');
    const spinner = document.getElementById('passwordSpinner');
    const btnText = document.getElementById('passwordBtnText');
    const submitBtn = document.getElementById('submitPasswordBtn');

    const code = (input?.value || '').trim();
    if (!code) {
      if (feedback) {
        feedback.className = 'modal-feedback error';
        feedback.textContent = 'Please enter the session password.';
        feedback.classList.remove('hidden');
      }
      hapticNotification('warning');
      return;
    }

    if (state.isSubmittingPassword) return;
    state.isSubmittingPassword = true;
    hapticImpact('medium');

    if (submitBtn) submitBtn.disabled = true;
    if (spinner) spinner.classList.remove('hidden');
    if (btnText) btnText.textContent = 'Submitting...';

    try {
      const response = await fetch('/api/password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ password: code })
      });

      const data = await response.json().catch(() => ({}));

      if (response.ok && (data.status === 'success' || data.success === true || data.result === 'SUBMITTED')) {
        hapticNotification('success');
        showToast('✅ Session password submitted successfully!', 'success');
        closePasswordModal();
        await fetchAttendanceStatus();
      } else {
        hapticNotification('error');
        if (feedback) {
          feedback.className = 'modal-feedback error';
          feedback.textContent = data.message || 'Incorrect password or session expired.';
          feedback.classList.remove('hidden');
        }
      }
    } catch (err) {
      hapticNotification('error');
      if (feedback) {
        feedback.className = 'modal-feedback error';
        feedback.textContent = 'Network error submitting password.';
        feedback.classList.remove('hidden');
      }
    } finally {
      state.isSubmittingPassword = false;
      if (submitBtn) submitBtn.disabled = false;
      if (spinner) spinner.classList.add('hidden');
      if (btnText) btnText.textContent = 'Submit Code';
    }
  }

  // --------------------------------------------------------------------------
  // 1-Tap SPeCTRUM SSO Gateway
  // --------------------------------------------------------------------------
  function connectWithSso(e) {
    const rawUrl = state.authConnectUrl || 'https://spectrum-proxy.yinjiasek.workers.dev/auth/connect';
    const authUrl = rawUrl.startsWith('http') ? rawUrl : (window.location.origin + rawUrl);
    console.log('[SPeCTRUM SSO] Launching SSO target:', authUrl);
    showToast('Opening SPeCTRUM SSO in browser...', 'info');

    const tg = getTg();
    let openedViaTg = false;
    if (tg && typeof tg.openLink === 'function') {
      try {
        tg.openLink(authUrl);
        openedViaTg = true;
        if (e) e.preventDefault();
      } catch (err) {
        console.warn('tg.openLink failed:', err);
      }
    }

    if (!openedViaTg && e && e.target && e.target.tagName !== 'A') {
      window.open(authUrl, '_blank');
    }

    // Start aggressive polling to detect when the session connects in background
    let attempts = 0;
    const maxAttempts = 30; // 30 * 2s = 60s
    if (state.ssoPollTimer) clearInterval(state.ssoPollTimer);

    state.ssoPollTimer = setInterval(async () => {
      attempts++;
      if (attempts > maxAttempts || state.authenticated) {
        clearInterval(state.ssoPollTimer);
        state.ssoPollTimer = null;
        return;
      }
      try {
        const res = await fetch('/api/status?refresh=true', { cache: 'no-store' });
        if (res.ok) {
          const d = await res.json();
          if (d.authenticated) {
            clearInterval(state.ssoPollTimer);
            state.ssoPollTimer = null;
            showToast('🎉 SPeCTRUM Cloud Session Connected!', 'success');
            fetchAttendanceStatus();
          }
        }
      } catch (e) {
        // ignore polling network errors
      }
    }, 2000);
  }

  // --------------------------------------------------------------------------
  // Native In-App Login Card
  // --------------------------------------------------------------------------
  async function submitLogin() {
    const emailInput = document.getElementById('loginEmail');
    const passwordInput = document.getElementById('loginPassword');
    const feedback = document.getElementById('loginFeedback');
    const spinner = document.getElementById('loginSpinner');
    const btnText = document.getElementById('loginBtnText');
    const submitBtn = document.getElementById('submitLoginBtn');

    const email = (emailInput?.value || '').trim();
    const password = (passwordInput?.value || '').trim();

    if (!email || !password) {
      if (feedback) {
        feedback.className = 'login-feedback feedback-error';
        feedback.textContent = 'Please provide both your UM Siswa email and password.';
        feedback.classList.remove('hidden');
      }
      hapticNotification('warning');
      return;
    }

    if (state.isLoggingIn) return;
    state.isLoggingIn = true;
    hapticImpact('medium');

    if (submitBtn) submitBtn.disabled = true;
    if (spinner) spinner.classList.remove('hidden');
    if (btnText) btnText.textContent = 'Authenticating...';

    if (feedback) {
      feedback.className = 'login-feedback feedback-info';
      feedback.textContent = 'Connecting to Microsoft Azure AD SSO...';
      feedback.classList.remove('hidden');
    }

    try {
      const response = await fetch('/api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({ email: email, password: password })
      });

      const data = await response.json().catch(() => ({}));

      if (response.ok && (data.status === 'success' || data.success === true || data.authenticated === true)) {
        hapticNotification('success');
        if (feedback) {
          feedback.className = 'login-feedback feedback-success';
          feedback.textContent = '✓ Cloud session established successfully!';
        }
        showToast('✅ Authenticated with SPeCTRUM!', 'success');
        if (passwordInput) passwordInput.value = '';
        state.authenticated = true;
        await fetchAttendanceStatus();
      } else {
        hapticNotification('error');
        if (feedback) {
          feedback.className = 'login-feedback feedback-error';
          feedback.textContent = data.message || 'Login failed. Please verify your credentials.';
        }
      }
    } catch (err) {
      hapticNotification('error');
      if (feedback) {
        feedback.className = 'login-feedback feedback-error';
        feedback.textContent = 'Network error connecting to login API.';
      }
    } finally {
      state.isLoggingIn = false;
      if (submitBtn) submitBtn.disabled = false;
      if (spinner) spinner.classList.add('hidden');
      if (btnText) btnText.textContent = 'Establish Cloud Session';
    }
  }

  function togglePasswordVisibility() {
    const passwordInput = document.getElementById('loginPassword');
    const eyeIcon = document.getElementById('eyeIcon');
    if (!passwordInput) return;

    hapticSelection();
    if (passwordInput.type === 'password') {
      passwordInput.type = 'text';
      if (eyeIcon) {
        eyeIcon.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line>';
      }
    } else {
      passwordInput.type = 'password';
      if (eyeIcon) {
        eyeIcon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle>';
      }
    }
  }

  // --------------------------------------------------------------------------
  // Event Listeners & Bootstrapping
  // --------------------------------------------------------------------------
  function setupEventListeners() {
    // Refresh Button
    const refreshBtn = document.getElementById('refreshBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        hapticImpact('light');
        fetchAttendanceStatus();
      });
    }

    // 1-Tap Check Attendance Button
    const checkBtn = document.getElementById('checkAttendanceBtn');
    if (checkBtn) {
      checkBtn.addEventListener('click', triggerCheckAttendance);
    }

    // Password Modal Events
    const submitPwBtn = document.getElementById('submitPasswordBtn');
    if (submitPwBtn) submitPwBtn.addEventListener('click', submitPassword);

    const cancelPwBtn = document.getElementById('cancelPasswordBtn');
    if (cancelPwBtn) cancelPwBtn.addEventListener('click', closePasswordModal);

    const pwInput = document.getElementById('sessionPasswordInput');
    if (pwInput) {
      pwInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          submitPassword();
        }
      });
    }

    const modalBackdrop = document.getElementById('passwordModal');
    if (modalBackdrop) {
      modalBackdrop.addEventListener('click', (e) => {
        if (e.target === modalBackdrop) {
          closePasswordModal();
        }
      });
    }

    // 1-Tap SSO Button Event
    const ssoBtn = document.getElementById('ssoConnectBtn');
    if (ssoBtn) ssoBtn.addEventListener('click', connectWithSso);

    // Login Form Events
    const loginForm = document.getElementById('loginForm');
    if (loginForm) loginForm.addEventListener('submit', (e) => {
      e.preventDefault();
      submitLogin();
    });

    const submitLoginBtn = document.getElementById('submitLoginBtn');
    if (submitLoginBtn) submitLoginBtn.addEventListener('click', submitLogin);

    const togglePwBtn = document.getElementById('togglePasswordVisibility');
    if (togglePwBtn) togglePwBtn.addEventListener('click', togglePasswordVisibility);

    // Auto-refresh interval (every 60 seconds)
    setInterval(() => {
      if (!document.hidden) {
        fetchAttendanceStatus();
      }
    }, 60000);
  }

  // Application Initialization (Safe for both dynamic and static loading)
  function startApp() {
    initTelegram();
    renderCourseCards();
    renderWeeklyTimeline();
    setupEventListeners();
    fetchAttendanceStatus();
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    startApp();
  } else {
    document.addEventListener('DOMContentLoaded', startApp);
  }

})();
