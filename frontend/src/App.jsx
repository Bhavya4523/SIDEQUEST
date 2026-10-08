import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_URL = "http://127.0.0.1:8000";

const moods = [
  "bored",
  "curious",
  "calm",
  "energetic",
  "adventurous",
];

const interests = [
  "food",
  "architecture",
  "nature",
  "people",
  "photography",
];

function getLocalDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

function formatJournalDate(dateString) {
  const date = new Date(dateString);

  return date.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function LocalStatus({ isOnline }) {
  return (
    <div className="local-status-group">
      <div className="topbar-status">
        <span className="status-dot" />
        {isOnline ? "LOCAL AI" : "NETWORK OFF"}
      </div>

      <span className="local-status-sub">
        {isOnline ? "ON DEVICE" : "LOCAL AI READY"}
      </span>
    </div>
  );
}

function App() {
  const [destination, setDestination] = useState("");
  const [timeAvailable, setTimeAvailable] = useState(30);
  const [mood, setMood] = useState("curious");
  const [selectedInterests, setSelectedInterests] = useState([]);

  const [quest, setQuest] = useState(null);
  const [questId, setQuestId] = useState(null);
  const [score, setScore] = useState(null);

  const [stats, setStats] = useState(null);
  const [history, setHistory] = useState([]);
  const [journalLoading, setJournalLoading] = useState(false);

  const [mode, setMode] = useState("setup");

  const [completionStatus, setCompletionStatus] = useState("");
  const [rating, setRating] = useState(null);
  const [reflection, setReflection] = useState("");

  const [loading, setLoading] = useState(false);
  const [chaosLoading, setChaosLoading] = useState(false);
  const [savingFeedback, setSavingFeedback] = useState(false);

  const [error, setError] = useState("");
  const [feedbackMessage, setFeedbackMessage] = useState("");

  const [darkMode, setDarkMode] = useState(() => {
    return localStorage.getItem("sidequest-dark-mode") === "true";
  });

  const [isOnline, setIsOnline] = useState(() => {
    return navigator.onLine;
  });

  useEffect(() => {
    localStorage.setItem(
      "sidequest-dark-mode",
      String(darkMode)
    );
  }, [darkMode]);

  useEffect(() => {
    function handleOnline() {
      setIsOnline(true);
    }

    function handleOffline() {
      setIsOnline(false);
    }

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  async function loadStats() {
    try {
      const response = await fetch(`${API_URL}/stats`);

      if (!response.ok) {
        return;
      }

      const data = await response.json();
      setStats(data);
    } catch {
      // Stats are optional.
    }
  }

  async function loadHistory() {
    setJournalLoading(true);

    try {
      const response = await fetch(`${API_URL}/quests`);

      if (!response.ok) {
        throw new Error("Could not load the field journal.");
      }

      const data = await response.json();

      const records = Array.isArray(data)
        ? data
        : data.value || [];

      setHistory(records);
    } catch (err) {
      setError(
        err.message || "Could not load the field journal."
      );
    } finally {
      setJournalLoading(false);
    }
  }

  useEffect(() => {
    loadStats();
  }, []);

  const weeklyData = useMemo(() => {
    const today = new Date();
    const days = [];

    for (let index = 6; index >= 0; index -= 1) {
      const date = new Date(today);
      date.setHours(0, 0, 0, 0);
      date.setDate(today.getDate() - index);

      const key = getLocalDateKey(date);

      const minutes = history
        .filter((record) => {
          if (record.status !== "completed") {
            return false;
          }

          if (!record.created_at) {
            return false;
          }

          return (
            getLocalDateKey(new Date(record.created_at)) === key
          );
        })
        .reduce(
          (total, record) =>
            total + Number(record.duration_minutes || 0),
          0
        );

      days.push({
        key,
        label: date.toLocaleDateString("en-IN", {
          weekday: "short",
        }),
        dateLabel: date.toLocaleDateString("en-IN", {
          day: "numeric",
          month: "short",
        }),
        minutes,
      });
    }

    return days;
  }, [history]);

  const weekMinutes = weeklyData.reduce(
    (total, day) => total + day.minutes,
    0
  );

  const completedHistory = history.filter(
    (record) => record.status === "completed"
  );

  async function openJournal() {
    setError("");
    await loadHistory();
    setMode("journal");
  }

  function toggleInterest(interest) {
    setSelectedInterests((current) =>
      current.includes(interest)
        ? current.filter((item) => item !== interest)
        : [...current, interest]
    );
  }

  async function createSidequest(event) {
    event.preventDefault();

    if (!destination.trim()) {
      setError("Tell us where you're going.");
      return;
    }

    setLoading(true);
    setError("");
    setQuest(null);
    setQuestId(null);
    setScore(null);
    setMode("setup");

    try {
      const response = await fetch(`${API_URL}/generate-quest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          destination: destination.trim(),
          time_available: Number(timeAvailable),
          mood,
          interests: selectedInterests,
        }),
      });

      if (!response.ok) {
        throw new Error("Could not create your sidequest.");
      }

      const data = await response.json();

      if (!data.quest) {
        throw new Error(
          data.error || "Could not create a safe sidequest."
        );
      }

      setQuest(data.quest);
      setQuestId(data.id);
      setScore(data.score);
      setMode("quest");
    } catch (err) {
      setError(
        err.message || "Something went wrong. Please try again."
      );
    } finally {
      setLoading(false);
    }
  }

  async function createChaosQuest() {
    setChaosLoading(true);
    setError("");
    setQuest(null);
    setQuestId(null);
    setScore(null);

    try {
      const response = await fetch(`${API_URL}/chaos-quest`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          time_available: Number(timeAvailable),
        }),
      });

      if (!response.ok) {
        throw new Error("Could not create a chaos quest.");
      }

      const data = await response.json();

      if (!data.quest) {
        throw new Error(
          data.error || "Could not create a chaos quest."
        );
      }

      setQuest(data.quest);
      setQuestId(data.id);
      setScore(data.score);
      setMode("quest");
    } catch (err) {
      setError(
        err.message || "Something went wrong. Please try again."
      );
    } finally {
      setChaosLoading(false);
    }
  }

  function startQuest() {
    setMode("phone-down");
  }

  function returnFromQuest() {
    setMode("completion");
  }

  async function submitFeedback() {
    if (!questId) {
      setError("Quest ID is missing.");
      return;
    }

    if (!completionStatus) {
      setError("Tell us whether you completed the quest.");
      return;
    }

    setSavingFeedback(true);
    setError("");

    try {
      const response = await fetch(
        `${API_URL}/quests/${questId}/feedback`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            status: completionStatus,
            rating,
            reflection: reflection.trim() || null,
          }),
        }
      );

      if (!response.ok) {
        throw new Error("Could not save your reflection.");
      }

      const data = await response.json();

      setFeedbackMessage(data.message || "Feedback saved.");

      await loadStats();
      await loadHistory();

      setMode("finished");
    } catch (err) {
      setError(
        err.message || "Could not save your feedback."
      );
    } finally {
      setSavingFeedback(false);
    }
  }

  function resetQuest() {
    setQuest(null);
    setQuestId(null);
    setScore(null);
    setCompletionStatus("");
    setRating(null);
    setReflection("");
    setFeedbackMessage("");
    setError("");
    setMode("setup");
  }

  const themeClass = darkMode ? "dark-theme" : "";

  if (mode === "journal") {
    return (
      <main className={`journal-screen ${themeClass}`}>
        <div className="field-background" />

        <header className="topbar">
          <div className="brand">
            <span className="brand-mark">S</span>
            <span>SIDEQUEST</span>
          </div>

          <div className="topbar-actions">
            <LocalStatus isOnline={isOnline} />

            <button
              className="theme-toggle"
              type="button"
              onClick={() =>
                setDarkMode((current) => !current)
              }
              aria-label="Toggle dark mode"
            >
              {darkMode ? "☀" : "☾"}
            </button>
          </div>
        </header>

        <section className="journal-section">
          <div className="journal-header">
            <div>
              <p className="field-note">
                FIELD JOURNAL
              </p>

              <h1>Places you've<br />noticed.</h1>

              <p className="journal-intro">
                A record of the moments you chose the longer way.
              </p>
            </div>

            <button
              className="text-button journal-back"
              type="button"
              onClick={resetQuest}
            >
              ← Back to journey
            </button>
          </div>

          <div className="journal-overview">
            <div className="journal-overview-item">
              <span>QUESTS</span>
              <strong>{completedHistory.length}</strong>
            </div>

            <div className="journal-overview-item">
              <span>THIS WEEK</span>
              <strong>{weekMinutes}m</strong>
            </div>

            <div className="journal-overview-item">
              <span>ALL TIME</span>
              <strong>
                {stats?.minutes_explored || 0}m
              </strong>
            </div>
          </div>

          <div className="week-section">
            <div className="section-heading">
              <div>
                <small>EXPLORATION</small>
                <h2>Last 7 days</h2>
              </div>

              <span>
                {weekMinutes} minutes outside
              </span>
            </div>

            <div className="week-bars">
              {weeklyData.map((day) => {
                const maxMinutes = Math.max(
                  ...weeklyData.map(
                    (item) => item.minutes
                  ),
                  1
                );

                const height =
                  day.minutes === 0
                    ? 8
                    : Math.max(
                        12,
                        (day.minutes / maxMinutes) * 100
                      );

                return (
                  <div
                    className="week-day"
                    key={day.key}
                  >
                    <div className="week-bar-area">
                      <div
                        className={`week-bar ${
                          day.minutes
                            ? "active"
                            : ""
                        }`}
                        style={{
                          height: `${height}%`,
                        }}
                      >
                        {day.minutes > 0 && (
                          <span>
                            {day.minutes}
                          </span>
                        )}
                      </div>
                    </div>

                    <strong>{day.label}</strong>
                    <small>{day.dateLabel}</small>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="journal-divider">
            <span />
            <small>YOUR FIELD NOTES</small>
            <span />
          </div>

          {journalLoading ? (
            <div className="journal-empty">
              <span className="journal-loader" />
              OPENING JOURNAL...
            </div>
          ) : completedHistory.length === 0 ? (
            <div className="journal-empty">
              <strong>Your first field note is waiting.</strong>
              <span>
                Complete a SIDEQUEST and it will appear here.
              </span>
            </div>
          ) : (
            <div className="journal-grid">
              {completedHistory.map((record) => (
                <article
                  className="passport-card"
                  key={record.id}
                >
                  <div className="passport-top">
                    <span>
                      FIELD NOTE #{record.id}
                    </span>

                    <span>
                      {formatJournalDate(
                        record.created_at
                      )}
                    </span>
                  </div>

                  <div className="passport-stamp">
                    <span>✓</span>
                    COMPLETED
                  </div>

                  <p className="passport-category">
                    {record.category}
                  </p>

                  <h3>{record.title}</h3>

                  <div className="passport-meta">
                    <span>
                      {record.duration_minutes} MIN
                    </span>

                    <span>
                      {record.difficulty}
                    </span>

                    {record.rating && (
                      <span>
                        {"★".repeat(record.rating)}
                      </span>
                    )}
                  </div>

                  {record.reflection && (
                    <blockquote>
                      “{record.reflection}”
                    </blockquote>
                  )}

                  <div className="passport-destination">
                    <span>DEToured FROM</span>
                    <strong>
                      {record.destination}
                    </strong>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>
    );
  }

  if (mode === "phone-down") {
    return (
      <main className={`phone-down-screen ${themeClass}`}>
        <div className="phone-down-grain" />

        <div className="phone-down-inner">
          <div className="mission-stamp">
            MISSION {questId}
          </div>

          <p className="phone-down-overline">
            THE SCREEN ENDS HERE
          </p>

          <h1>
            PHONE
            <br />
            DOWN.
          </h1>

          <p className="phone-down-main">
            Go live the quest.
          </p>

          <div className="phone-down-line" />

          <p className="phone-down-sub">
            Come back when you're done.
          </p>

          <button
            className="return-button"
            type="button"
            onClick={returnFromQuest}
          >
            I'M BACK
          </button>
        </div>
      </main>
    );
  }

  if (mode === "completion") {
    return (
      <main className={`completion-screen ${themeClass}`}>
        <div className="field-background" />

        <div className="completion-inner">
          <div className="screen-top">
            <div className="field-label">
              FIELD NOTE · RETURN
            </div>

            <button
              className="theme-toggle"
              type="button"
              onClick={() =>
                setDarkMode((current) => !current)
              }
              aria-label="Toggle dark mode"
            >
              {darkMode ? "☀" : "☾"}
            </button>
          </div>

          <p className="eyebrow">Welcome back.</p>

          <h1>How did the detour go?</h1>

          <div className="completion-options">
            {[
              ["completed", "YES", "Made it happen"],
              ["partly", "PARTLY", "Some of it"],
              ["skipped", "NO", "Not this time"],
            ].map(([value, label, helper]) => (
              <button
                key={value}
                type="button"
                className={`completion-button ${
                  completionStatus === value
                    ? "selected"
                    : ""
                }`}
                onClick={() =>
                  setCompletionStatus(value)
                }
              >
                <strong>{label}</strong>
                <span>{helper}</span>
              </button>
            ))}
          </div>

          <div className="feedback-section">
            <p className="feedback-label">
              RATE THE ADVENTURE
            </p>

            <div className="rating-row">
              {[1, 2, 3, 4, 5].map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`rating-button ${
                    rating === value ? "selected" : ""
                  }`}
                  onClick={() => setRating(value)}
                >
                  {value}
                </button>
              ))}
            </div>

            <textarea
              value={reflection}
              onChange={(event) =>
                setReflection(event.target.value)
              }
              placeholder="What did you notice that you normally miss?"
              rows={4}
            />

            {error && (
              <div className="error-message">
                {error}
              </div>
            )}

            <button
              className="create-button"
              type="button"
              onClick={submitFeedback}
              disabled={savingFeedback}
            >
              <span>
                {savingFeedback
                  ? "SAVING FIELD NOTE..."
                  : "SAVE FIELD NOTE"}
              </span>
              <span>↗</span>
            </button>
          </div>
        </div>
      </main>
    );
  }

  if (mode === "finished") {
    return (
      <main className={`completion-screen ${themeClass}`}>
        <div className="field-background" />

        <div className="finished-inner">
          <div className="screen-top">
            <div className="field-label">
              FIELD NOTE · {questId}
            </div>

            <button
              className="theme-toggle"
              type="button"
              onClick={() =>
                setDarkMode((current) => !current)
              }
              aria-label="Toggle dark mode"
            >
              {darkMode ? "☀" : "☾"}
            </button>
          </div>

          <span className="finished-mark">✓</span>

          <p className="eyebrow">Quest complete.</p>

          <h1>That was the point.</h1>

          <p className="finished-copy">
            A little less screen. A little more world.
          </p>

          {feedbackMessage && (
            <p className="saved-message">
              {feedbackMessage}
            </p>
          )}

          <button
            className="create-button"
            type="button"
            onClick={resetQuest}
          >
            <span>START ANOTHER DETOUR</span>
            <span>↗</span>
          </button>

          <button
            className="journal-link-button"
            type="button"
            onClick={openJournal}
          >
            OPEN FIELD JOURNAL →
          </button>
        </div>
      </main>
    );
  }

  if (mode === "quest") {
    return (
      <main className={`app-shell ${themeClass}`}>
        <div className="field-background" />

        <header className="topbar">
          <div className="brand">
            <span className="brand-mark">S</span>
            <span>SIDEQUEST</span>
          </div>

          <div className="topbar-actions">
            <LocalStatus isOnline={isOnline} />

            <button
              className="journal-top-button"
              type="button"
              onClick={openJournal}
            >
              JOURNAL
            </button>

            <button
              className="theme-toggle"
              type="button"
              onClick={() =>
                setDarkMode((current) => !current)
              }
              aria-label="Toggle dark mode"
            >
              {darkMode ? "☀" : "☾"}
            </button>
          </div>
        </header>

        <section className="quest-section">
          <div className="quest-header">
            <button
              className="text-button"
              type="button"
              onClick={resetQuest}
            >
              ← New sidequest
            </button>

            <div className="quest-header-right">
              <span className="mission-number">
                #{questId}
              </span>

              {score !== null && (
                <span className="score-label">
                  MATCH {Math.round(score * 100)}%
                </span>
              )}
            </div>
          </div>

          <div className="quest-card">
            <div className="quest-kicker">
              <span>FIELD MISSION</span>
              <span>{quest.category}</span>
            </div>

            <div className="quest-meta">
              <span>{quest.duration_minutes} MIN</span>
              <span>•</span>
              <span>{quest.difficulty}</span>
              <span>•</span>
              <span>REAL WORLD</span>
            </div>

            <h1>{quest.title}</h1>

            <p className="quest-objective">
              {quest.objective}
            </p>

            <div className="detour-divider">
              <span />
              <small>YOUR DETOUR</small>
              <span />
            </div>

            <div className="quest-steps">
              {quest.steps.map((step, index) => (
                <div
                  className="quest-step"
                  key={`${questId}-${index}`}
                >
                  <span>
                    {String(index + 1).padStart(2, "0")}
                  </span>

                  <p>{step}</p>
                </div>
              ))}
            </div>

            <div className="safety-box">
              <strong>FIELD RULES</strong>

              {quest.safety_notes.map((note) => (
                <p key={note}>• {note}</p>
              ))}
            </div>

            <button
              className="go-button-large"
              type="button"
              onClick={startQuest}
            >
              <span>GO OUTSIDE</span>
              <span>↗</span>
            </button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className={`app-shell ${themeClass}`}>
      <div className="field-background" />

      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">S</span>
          <span>SIDEQUEST</span>
        </div>

        <div className="topbar-actions">
          <LocalStatus isOnline={isOnline} />

          <button
            className="journal-top-button"
            type="button"
            onClick={openJournal}
          >
            JOURNAL
          </button>

          <button
            className="theme-toggle"
            type="button"
            onClick={() =>
              setDarkMode((current) => !current)
            }
            aria-label="Toggle dark mode"
          >
            {darkMode ? "☀" : "☾"}
          </button>
        </div>
      </header>

      <section className="home-section">
        <div className="hero-copy">
          <div className="field-note">
            FIELD NOTE 001
            <span />
            LOCAL AI
          </div>

          <p className="eyebrow">
            A different way home
          </p>

          <h1>
            Your destination
            <br />
            <em>isn't the point.</em>
          </h1>

          <p className="hero-description">
            SIDEQUEST turns ordinary journeys into tiny
            real-world adventures. Tell us where you're going.
            We'll give you a reason to notice the way there.
          </p>

          <div className="hero-manifesto">
            <span>PLAN</span>
            <b>→</b>
            <span>GO</span>
            <b>→</b>
            <span>NOTICE</span>
          </div>
        </div>

        <div className="home-controls">
          {stats && (
            <div className="stats-strip">
              <div>
                <span>COMPLETED</span>
                <strong>{stats.sidequests_completed}</strong>
              </div>

              <div>
                <span>MINUTES OUTSIDE</span>
                <strong>{stats.minutes_explored}</strong>
              </div>

              <div>
                <span>CATEGORIES</span>
                <strong>{stats.categories_explored}</strong>
              </div>
            </div>
          )}

          <div
            className={`network-note ${
              isOnline ? "" : "offline"
            }`}
          >
            <span className="network-note-dot" />

            <span>
              {isOnline
                ? "LOCAL AI · ON DEVICE"
                : "NETWORK OFF · LOCAL AI STILL READY"}
            </span>
          </div>

          <form
            className="quest-form"
            onSubmit={createSidequest}
          >
            <div className="form-heading">
              <span>01</span>

              <div>
                <small>DESTINATION</small>
                <h2>Where are you going?</h2>
              </div>
            </div>

            <input
              className="destination-input"
              type="text"
              value={destination}
              onChange={(event) =>
                setDestination(event.target.value)
              }
              placeholder="Home, college, station..."
            />

            <div className="form-heading">
              <span>02</span>

              <div>
                <small>WINDOW</small>
                <h2>How much time do you have?</h2>
              </div>
            </div>

            <div className="time-row">
              {[15, 20, 30, 45, 60].map((minutes) => (
                <button
                  key={minutes}
                  type="button"
                  className={`choice-button ${
                    timeAvailable === minutes
                      ? "selected"
                      : ""
                  }`}
                  onClick={() =>
                    setTimeAvailable(minutes)
                  }
                >
                  {minutes}m
                </button>
              ))}
            </div>

            <div className="form-heading">
              <span>03</span>

              <div>
                <small>MOOD</small>
                <h2>What's your energy?</h2>
              </div>
            </div>

            <div className="choice-grid">
              {moods.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`choice-button ${
                    mood === item ? "selected" : ""
                  }`}
                  onClick={() => setMood(item)}
                >
                  {item}
                </button>
              ))}
            </div>

            <div className="form-heading">
              <span>04</span>

              <div>
                <small>INTERESTS</small>
                <h2>What catches your eye?</h2>
              </div>
            </div>

            <div className="choice-grid">
              {interests.map((interest) => (
                <button
                  key={interest}
                  type="button"
                  className={`choice-button ${
                    selectedInterests.includes(interest)
                      ? "selected"
                      : ""
                  }`}
                  onClick={() =>
                    toggleInterest(interest)
                  }
                >
                  {interest}
                </button>
              ))}
            </div>

            {error && (
              <div className="error-message">
                {error}
              </div>
            )}

            <button
              className="create-button"
              type="submit"
              disabled={loading}
            >
              <span>
                {loading
                  ? "DREAMING UP A DETOUR..."
                  : "CREATE SIDEQUEST"}
              </span>

              <span>↗</span>
            </button>

            <button
              className="chaos-button"
              type="button"
              onClick={createChaosQuest}
              disabled={chaosLoading}
            >
              <span>
                {chaosLoading
                  ? "DREAMING UP CHAOS..."
                  : "CHAOS MODE"}
              </span>

              <small>
                {timeAvailable} MINUTES · NO PLAN
              </small>

              <span>↗</span>
            </button>
          </form>
        </div>
      </section>

      <footer>
        <span>LOCAL AI · PRIVATE BY DEFAULT</span>
        <span>THE WORLD IS OUTSIDE</span>
      </footer>
    </main>
  );
}

export default App;