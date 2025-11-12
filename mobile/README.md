# Fleet Mobile (Expo)

A minimal, user-friendly mobile wrapper for the Fleet web application. This MVP uses a WebView to load your existing Django site, giving you immediate mobile usability while we iterate towards fully native screens.

## Quick Start

1. Prereqs:
   - Node 18+ and npm (or yarn/pnpm)
   - Expo CLI (optional): `npm i -g expo` (or use `npx`)
   - Android Studio / Xcode if running on device simulators

2. Configure the base URL the app should load:

   - Preferred: set an environment variable before starting Expo:

     - macOS/Linux: `export EXPO_PUBLIC_WEB_BASE_URL="https://your-domain.com"`
     - Windows (Powershell): `$Env:EXPO_PUBLIC_WEB_BASE_URL = "https://your-domain.com"`

   - Default (if unset): `http://localhost:8000/`

   Notes:
   - For Android emulators, `localhost` refers to the emulator. Use your machine's LAN IP (e.g. `http://192.168.1.xx:8000`) or `http://10.0.2.2:8000` for the standard Android emulator.
   - Ensure your Django `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` permit the mobile host.

3. Install and run:

```
cd mobile
npm install
npm run start
```

Then press `a` for Android, `i` for iOS, or scan the QR with Expo Go.

## What’s included

- WebView wrapper with:
  - External links opening in the system browser
  - Android hardware back support
  - Bottom toolbar (Back/Forward/Refresh/Home)
  - Loading indicator overlay
  - Custom User-Agent: `FleetApp/0.1` to allow server-side mobile targeting

## Phase 2: Native app

To deliver a richer, offline-friendly mobile experience, we can:
- Add a REST API layer (Django REST Framework) for auth, drivers, trips, tasks, reports
- Build native screens (home/dashboard, jobs/trips, vehicle list, tasks/forms, notifications)
- Implement secure auth (session via WebView today; tokens/OAuth for native flows later)
- Add push notifications, background sync, and offline caching

If you want, I can start by introducing DRF endpoints in this Django repo and then replace WebView screens incrementally with native ones.

## Troubleshooting

- Blank screen or redirect loops:
  - Verify `EXPO_PUBLIC_WEB_BASE_URL` is reachable from the device and allowed by Django settings
- File uploads/geolocation:
  - Android permissions are declared in `app.json` and WebView allows file access; ensure your site prompts as needed
- CSRF / cookies:
  - The WebView uses the system webview cookie jar; make sure cookie and CSRF settings allow mobile access

