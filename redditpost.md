# Reddit post and GitHub description for Fuzzy Journey

Repository: https://github.com/aryan-nikzad/fuzzy-journey

## Reddit title options (pick one)

1. I built a day planner around the body's natural rhythm, for people who plan a lot and do little (Linux, open source)
2. Fuzzy Journey: wake, work and sleep times based on the sun, for perfectionists who procrastinate
3. A minimal Linux app that shapes your day without blocking your life

## Reddit post body

Hi everyone,

I built this app for myself, and I think it might help some of you too.

**Who I made it for**

I am a perfectionist and I used to procrastinate a lot. I would plan and plan, and then not actually work. I wanted something that removes the guessing: when to wake, when to start working, when to stop, when to sleep. Less to remember, less to decide.

**The idea**

The app is built around the body's natural clock. It uses the sun's position to decide your day, from dawn to night. I use the Islamic prayer times for this because they are very precise sun-based times. That is the only reason. This is not a religious app and it is not built around prayer.

From that, it tells you:

- When to wake up and when to sleep
- When to start and stop working if you want to use 50% (Steady) or 75% (Push) of your day
- It counts your real life too. If you go to the gym for 2 hours or call someone for 2 hours, it subtracts that time, so the plan still adds up
- Rest days are earned: two Push days buy one Rest day

It does not block your life. It shapes it. Your normal life continues, and the app moves the work around it.

**What is inside**

- A timeline of the day, with alarms that ring even when the window is closed (and you can stop them from the app or from the notification)
- **Pomodoro** inside your work time. Focus length, breaks and long breaks are adjustable and can be turned off
- **Tasks** with a length and a status, and a Tomorrow screen. A day's tasks can never be more than its focus time, so you cannot plan more than you can do
- **"I overslept" mode:** the day starts when you really woke up, and you still work 50% of the time you are awake
- **Night work:** possible, but marked "not recommended". It first suggests moving tasks to tomorrow, and it shows the sleep it costs
- Everything stays on your computer. No account, no cloud

**For Muslims, and for everyone else**

The app is not an Islamic app, but it does give Muslims what they need: prayer alarms and azan sounds (each can be switched off), and a simple prayer tracker where the five prayers are zero-length tasks that never count as work time. There are no scores and no streaks.

If you are not Muslim, you can ignore all of that. Just use the prayer times as anchors in your day, as fixed points to plan your tasks around.

**Who it may help most**

Probably people who control their own time: freelancers, founders, CEOs, people who work for themselves. If your hours are decided by an employer, it will be less useful, because the app needs you to own your day.

**Right now it is Linux only**

Today it is only a Linux app (GTK 4 / libadwaita). I hope to port it to Windows and Android later. I think it is not too hard, but I need the time. If someone else wants to do a port, or any other improvement, and sends it to my GitHub as a pull request, I will be very grateful.

**About the code (please read)**

Most of the code was written by AI. It was not made in one go. It started as a small command line tool and evolved over many sessions into a GUI app. I directed the design and the rules, and the AI wrote most of the code. It has tests, but it is young software, so expect bugs. If you do not like AI-written code, that is completely fine. Please just move on. I made this to help people, not to argue.

English is not my first language, so I got help writing this post.

**Link**

GitHub: https://github.com/aryan-nikzad/fuzzy-journey

I really hope it helps someone who has the same perfectionism and discipline problems I had. If you try it, I would love to hear what worked and what did not. Thank you for reading.

## GitHub description (pick one)

Longer:

> A minimal Linux app that shapes your day around the body's natural clock: when to wake, work and sleep, with pomodoro, tasks and alarms. Built for perfectionists who plan but don't do.

Shorter, closer to the first one:

> Minimal Linux day planner. Tells you when to wake, work and sleep from the sun's times, even around gym and calls. For people who plan too much and do too little.

Suggested topics: `linux`, `gtk4`, `libadwaita`, `productivity`, `pomodoro`, `time-management`, `python`, `prayer-times`

## Notes before posting

- Add two or three screenshots from `docs/screenshots` (`today-dark.png` and `tomorrow-dark.png` look best).
- Check each subreddit's rules first. Some need a flair or a disclosure for AI-assisted projects.
- Do not add claims like "scientifically proven". The app does not prove them.
- Today the prayer tracker row in the task list cannot be turned off, only the prayer alarms and azan can. The post says exactly that. If you add a switch for the tracker, update the "For Muslims" section.
