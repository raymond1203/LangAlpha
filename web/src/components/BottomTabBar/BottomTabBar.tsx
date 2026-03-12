import { ChartCandlestick, LayoutDashboard, MessageSquareText, Timer, Settings } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import './BottomTabBar.css';

const menuItems = [
  { key: '/dashboard', icon: LayoutDashboard, labelKey: 'sidebar.dashboard' },
  { key: '/chat', icon: MessageSquareText, labelKey: 'sidebar.chatAgent' },
  { key: '/market', icon: ChartCandlestick, labelKey: 'sidebar.marketView' },
  { key: '/automations', icon: Timer, labelKey: 'sidebar.automations' },
  { key: '/settings', icon: Settings, labelKey: 'sidebar.settings' },
];

export default function BottomTabBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const handleItemClick = (path: string) => {
    navigate(path);
  };

  return (
    <div className="bottom-tab-bar">
      <div className="bottom-tab-bar-pill">
        {menuItems.map((item) => {
          const Icon = item.icon;
          const isActive = item.key === '/chat'
            ? location.pathname.startsWith('/chat')
            : location.pathname === item.key || location.pathname.startsWith(item.key + '/');

          return (
            <button
              key={item.key}
              className={`bottom-tab-item ${isActive ? 'active' : ''}`}
              onClick={() => handleItemClick(item.key)}
              aria-label={t(item.labelKey)}
              aria-current={isActive ? 'page' : undefined}
            >
              <Icon className="bottom-tab-item-icon" />
            </button>
          );
        })}
      </div>
    </div>
  );
}
