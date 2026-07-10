import {
  LeftOutlined,
  RightOutlined,
} from '@ant-design/icons';
import { Button, Tooltip } from 'antd';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  buildGridTemplate,
  clampWidth,
  createDefaultLayout,
  loadLayoutState,
  PANEL_LABELS,
  saveLayoutState,
  type MailboxLayoutState,
  type PanelKey,
} from '@/utils/mailboxLayout';

type Props = {
  userId?: string;
  groups: React.ReactNode;
  accounts: React.ReactNode;
  emails: React.ReactNode;
  /** 外部触发重置时递增 */
  resetToken?: number;
};

const COLLAPSED_W = 36;

/**
 * 三栏可拖拽工作台：分组 | 账号 | 邮件
 * 对齐旧 LayoutManager：拖拽改宽、折叠/展开、localStorage 持久化
 */
const ResizableWorkbench: React.FC<Props> = ({
  userId = 'guest',
  groups,
  accounts,
  emails,
  resetToken = 0,
}) => {
  const [layout, setLayout] = useState<MailboxLayoutState>(() =>
    loadLayoutState(userId),
  );
  const layoutRef = useRef(layout);
  layoutRef.current = layout;

  const dragRef = useRef<{
    panel: PanelKey;
    startX: number;
    startWidth: number;
  } | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setLayout(loadLayoutState(userId));
  }, [userId]);

  useEffect(() => {
    if (resetToken > 0) {
      const next = createDefaultLayout(userId);
      setLayout(next);
      saveLayoutState(next, userId);
    }
  }, [resetToken, userId]);

  const persistSoon = useCallback(
    (next: MailboxLayoutState) => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        saveLayoutState(next, userId);
      }, 500);
    },
    [userId],
  );

  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      // 卸载前立即落盘
      saveLayoutState(layoutRef.current, userId);
    };
  }, [userId]);

  const setPanelWidth = (panel: PanelKey, width: number) => {
    setLayout((prev) => {
      const next: MailboxLayoutState = {
        ...prev,
        panels: {
          ...prev.panels,
          [panel]: {
            ...prev.panels[panel],
            width: clampWidth(panel, width),
          },
        },
      };
      persistSoon(next);
      return next;
    });
  };

  const toggleCollapse = (panel: PanelKey) => {
    setLayout((prev) => {
      const next: MailboxLayoutState = {
        ...prev,
        panels: {
          ...prev.panels,
          [panel]: {
            ...prev.panels[panel],
            collapsed: !prev.panels[panel].collapsed,
          },
        },
      };
      saveLayoutState(next, userId);
      return next;
    });
  };

  const onResizerDown = (panel: PanelKey, e: React.MouseEvent) => {
    e.preventDefault();
    const state = layoutRef.current.panels[panel];
    if (state.collapsed) return;
    dragRef.current = {
      panel,
      startX: e.clientX,
      startWidth: state.width,
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      const delta = e.clientX - drag.startX;
      setPanelWidth(drag.panel, drag.startWidth + delta);
    };
    const onUp = () => {
      if (!dragRef.current) return;
      dragRef.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      saveLayoutState(layoutRef.current, userId);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    return () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
  }, [userId]);

  const onResizerKey = (panel: PanelKey, e: React.KeyboardEvent) => {
    if (layout.panels[panel].collapsed) return;
    const step = e.shiftKey ? 20 : 10;
    if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setPanelWidth(panel, layout.panels[panel].width - step);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      setPanelWidth(panel, layout.panels[panel].width + step);
    }
  };

  const renderPanel = (
    key: PanelKey,
    content: React.ReactNode,
    side: 'left' | 'right' = 'left',
  ) => {
    const collapsed = layout.panels[key].collapsed;
    return (
      <div
        data-panel={key}
        className="mailbox-panel"
        style={{
          minWidth: 0,
          height: '100%',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          border: '1px solid rgba(5, 5, 5, 0.06)',
          borderRadius: 8,
          background: 'var(--ant-color-bg-container, #fff)',
          position: 'relative',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: collapsed ? 'center' : 'space-between',
            padding: collapsed ? '8px 0' : '6px 8px',
            borderBottom: collapsed
              ? 'none'
              : '1px solid rgba(5, 5, 5, 0.06)',
            flexDirection: collapsed ? 'column' : 'row',
            gap: 4,
            minHeight: 36,
          }}
        >
          {!collapsed ? (
            <span style={{ fontWeight: 500, fontSize: 13 }}>
              {PANEL_LABELS[key]}
            </span>
          ) : (
            <span
              style={{
                writingMode: 'vertical-rl',
                fontSize: 12,
                fontWeight: 500,
                letterSpacing: 2,
              }}
            >
              {PANEL_LABELS[key]}
            </span>
          )}
          <Tooltip
            title={
              collapsed
                ? `展开${PANEL_LABELS[key]}面板`
                : `折叠${PANEL_LABELS[key]}面板`
            }
          >
            <Button
              type="text"
              size="small"
              aria-label={
                collapsed
                  ? `展开${PANEL_LABELS[key]}面板`
                  : `折叠${PANEL_LABELS[key]}面板`
              }
              icon={
                collapsed ? (
                  side === 'left' ? (
                    <RightOutlined />
                  ) : (
                    <LeftOutlined />
                  )
                ) : side === 'left' ? (
                  <LeftOutlined />
                ) : (
                  <RightOutlined />
                )
              }
              onClick={() => toggleCollapse(key)}
            />
          </Tooltip>
        </div>
        {!collapsed ? (
          <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
            {content}
          </div>
        ) : null}
      </div>
    );
  };

  const resizer = (forPanel: PanelKey) => (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={`调整${PANEL_LABELS[forPanel]}宽度`}
      tabIndex={0}
      data-resizer={forPanel}
      onMouseDown={(e) => onResizerDown(forPanel, e)}
      onKeyDown={(e) => onResizerKey(forPanel, e)}
      style={{
        width: 6,
        cursor: layout.panels[forPanel].collapsed ? 'default' : 'col-resize',
        background: 'transparent',
        position: 'relative',
        alignSelf: 'stretch',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: '20%',
          bottom: '20%',
          left: 2,
          width: 2,
          borderRadius: 1,
          background: 'rgba(5,5,5,0.12)',
        }}
      />
    </div>
  );

  return (
    <div
      className="mailbox-workbench"
      style={{
        display: 'grid',
        gridTemplateColumns: buildGridTemplate(layout.panels),
        gap: 0,
        minHeight: 560,
        height: 'calc(100vh - 220px)',
        minWidth: COLLAPSED_W * 3 + 12,
      }}
    >
      {renderPanel('groups', groups, 'left')}
      {resizer('groups')}
      {renderPanel('accounts', accounts, 'left')}
      {resizer('accounts')}
      {renderPanel('emails', emails, 'right')}
    </div>
  );
};

export default ResizableWorkbench;
