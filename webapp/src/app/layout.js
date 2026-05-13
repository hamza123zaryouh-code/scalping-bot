import './globals.css'
import AuthSessionProvider from '@/components/AuthSessionProvider'
import { ToastProvider } from '@/components/ToastProvider'
import ThemeProvider from '@/components/ThemeProvider'
import { I18nProvider } from '@/lib/i18n'
import Navbar from '@/components/Navbar'
import AppMain from '@/components/AppMain'
import AuthGate from '@/components/AuthGate'
import { ProfileProvider } from '@/components/ProfileProvider'
import ErrorBoundary from '@/components/ErrorBoundary'

export const metadata = {
  title: 'XAUUSD Expert Desk',
  description: 'Trading control surface for live monitoring, analytics and FTMO risk oversight.',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en" dir="ltr">
      <body className="min-h-screen antialiased">
        <I18nProvider>
          <ThemeProvider>
            <AuthSessionProvider>
              <ToastProvider>
                <ProfileProvider>
                  <AuthGate>
                    <Navbar />
                    <AppMain>
                      <ErrorBoundary>{children}</ErrorBoundary>
                    </AppMain>
                  </AuthGate>
                </ProfileProvider>
              </ToastProvider>
            </AuthSessionProvider>
          </ThemeProvider>
        </I18nProvider>
      </body>
    </html>
  )
}
