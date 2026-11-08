# Philosophy

> **The day is given. Work a share. Bank the rest. Protect the night.**

Fuzzy Journey is built on four ideas and two practices. Everything the app does
follows from them, and every rule below is implemented, and tested, in
[`fuzzy_journey/rhythm.py`](fuzzy_journey/rhythm.py). If a feature does not
serve one of these ideas, it does not belong in the app.

## Four ideas

### 1. The day is given.
**Fajr to Isha is your day.**

Prayer times, not arbitrary hours, set the edges of your day. Long summer days and short winter days both stay in proportion.

*In the app:* you wake at Fajr, and the day ends at Isha. Nothing else defines it.

### 2. Work a share.
**Give work a share of the day, not a number of hours.**

A Steady day gives 50% of the day to work; a Push day gives 75%. Work fills the morning first, until 14:00. The afternoon stays yours, and the evening is used only for what overflows.

*In the app:* the **Steady / Push / Rest** selector on the Today screen. A Steady day in January (Fajr 05:42, Isha 18:20, a 12 h 38 min day) is 6 h 19 min of work, finished before noon. A Push day is 9 h 28 min: 8 h 18 min in the morning, and the last 1 h 10 min from 18:00.

### 3. Bank the rest.
**Rest is earned, banked and spent.**

Each Push day banks half a day. Each Rest day spends a whole one, so two Push days buy one Rest day. The balance may go negative, but you always see it.

*In the app:* the **Bank** screen. Unmarked days count as Steady and change nothing.

### 4. Protect the night.
**Sleep is measured against the natural night.**

The night runs from Isha to the next Fajr. Evening work is the last resort, and its cost is shown honestly as sleep given up.

*In the app:* that January Push day ends at 19:10, so it shows "50m given up" next to bedtime. The cost of a push is never hidden.

## Two practices

### 5. Count focus, not clock time.
**A call or an errand pauses the work clock.**

The finish moves later, but the amount of work stays whole.

*In the app:* add a 07:30-08:00 call and a 05:42-12:01 work block finishes at 12:31, with the call drawn as a notch in the day bar.

### 6. Keep it yours.
**Everything lives on this computer.**

No account, no cloud. Alarms ring without internet.

*In the app:* the only network request is downloading a year's timetable, once.

## What it deliberately is not

- Not a project manager or a calendar. It shapes the *day*. Tasks are only what fits in a day's focus time: no projects, tags, due dates or priorities beyond order and importance.
- Not a productivity score. There are no streaks, no points, nothing to feel bad about.
- Not a prayer-time app. Prayer times are the *frame* of the day; the app does not teach or judge your practice.

## When the day goes wrong: a Recovered day

Sometimes you wake late. The Steady plan then asks for work that has already slipped away, so the day is rescued instead of abandoned. On a **Recovered** day the day begins when you really woke, and work is half of the time you are awake from then to Isha. It may run into the afternoon, which is the one place the afternoon is not yours.

It is a rescue, not a plan. It is never offered next to Steady, Push and Rest; it appears only as *I overslept…* on a Steady day. It is neutral for the bank (it counts as Steady), it never shortens your night, and the pomodoro, planning and tasks follow the new window like any other day.

## Night work: allowed, never recommended

*Protect the night* is a rule you can break on purpose. On any working day you can add one to four hours of **night work** after Isha. It is never the default and it is never offered quietly: the app first suggests moving tasks to tomorrow, which is almost always better for the work, for discipline and for health. If you still choose it, its price is shown in the same place as Push evening work: sleep given up. It is neutral for the bank, so it earns nothing.

