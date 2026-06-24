import type { Metadata } from 'next';
import './globals.css';
import ChatBot from '../components/ChatBot';

export const metadata: Metadata = {
  title: 'TestPilot AI',
  description: 'Multi-agent automated test generation platform',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#050508] text-[#e2e8f0] antialiased">
        {children}
        <ChatBot />
      </body>
    </html>
  );
}
