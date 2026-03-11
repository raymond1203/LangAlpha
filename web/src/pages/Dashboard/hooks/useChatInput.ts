import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useToast } from '../../../components/ui/use-toast';
import { getFlashWorkspace } from '../../ChatAgent/utils/api';
import { useWorkspaces } from '../../../hooks/useWorkspaces';
import type { Workspace } from '@/types/api';

type ChatMode = 'fast' | 'deep';

interface ChatAttachment {
  file: File;
  type: string;
  preview?: string | null;
  dataUrl: string | null;
}

interface SlashCommand {
  type: string;
  name: string;
  skillName?: string;
  description?: string;
  aliases?: string[];
}

interface SendOptions {
  model?: string | null;
  reasoningEffort?: string | null;
  fastMode?: boolean;
}

/**
 * Custom hook for handling chat input functionality
 * Manages mode (fast/deep), workspace selection, loading state, and workspace creation dialog
 * Message and planMode are managed internally by ChatInput and passed via handleSend.
 *
 * @returns {Object} Chat input state and handlers
 */
export function useChatInput() {
  const [mode, setMode] = useState<ChatMode>('fast');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const navigate = useNavigate();
  const { toast } = useToast();

  // Fetch workspaces for the workspace selector (shared cache with ChatAgent)
  const { data: wsData } = useWorkspaces({ limit: 50, offset: 0 });
  const workspaces = ((wsData as { workspaces?: Workspace[] })?.workspaces || []).filter((ws: Workspace) => ws.status !== 'flash');

  // Auto-select first workspace when data arrives
  useEffect(() => {
    if (workspaces.length > 0 && !selectedWorkspaceId) {
      setSelectedWorkspaceId(workspaces[0].workspace_id);
    }
  }, [workspaces, selectedWorkspaceId]);

  /**
   * Handles sending a message and navigating to the ChatAgent workspace.
   * Fast mode: uses flash workspace (agent_mode: flash)
   * Deep mode: uses selected workspace or falls back to default LangAlpha workspace
   */
  const handleSend = async (
    message: string,
    planMode = false,
    attachments: ChatAttachment[] = [],
    _slashCommands: SlashCommand[] = [],
    { model, reasoningEffort }: SendOptions = {},
  ): Promise<void> => {
    const hasContent = message.trim() || (attachments && attachments.length > 0);
    if (!hasContent || isLoading) {
      return;
    }

    setIsLoading(true);
    try {
      // Build additional context and attachment metadata from attachments
      let additionalContext: Array<{ type: string; data: string | null; description: string }> | null = null;
      let attachmentMeta: Array<{ name: string; type: string; size: number; preview: string | null; dataUrl: string | null }> | null = null;
      if (attachments && attachments.length > 0) {
        additionalContext = attachments.map((a) => ({
          type: 'image',
          data: a.dataUrl,
          description: a.file.name,
        }));
        attachmentMeta = attachments.map((a) => ({
          name: a.file.name,
          type: a.type,
          size: a.file.size,
          preview: a.preview || null,
          dataUrl: a.dataUrl,
        }));
      }

      if (mode === 'fast') {
        // Flash mode: get/create flash workspace and navigate
        const flashWs = await getFlashWorkspace() as { workspace_id: string };
        const workspaceId = flashWs.workspace_id;

        navigate(`/chat/t/__default__`, {
          state: {
            workspaceId,
            initialMessage: message.trim(),
            planMode: false,
            agentMode: 'flash',
            workspaceStatus: 'flash',
            ...(additionalContext ? { additionalContext } : {}),
            ...(attachmentMeta ? { attachmentMeta } : {}),
            ...(model ? { model } : {}),
            ...(reasoningEffort ? { reasoningEffort } : {}),
          },
        });
      } else {
        // Deep mode: use selected workspace or prompt user to create one
        let workspaceId = selectedWorkspaceId;
        if (!workspaceId) {
          toast({
            variant: 'destructive',
            title: 'No workspace selected',
            description: 'Please create a workspace first to use deep mode.',
          });
          return;
        }

        navigate(`/chat/t/__default__`, {
          state: {
            workspaceId,
            initialMessage: message.trim(),
            planMode: planMode,
            ...(additionalContext ? { additionalContext } : {}),
            ...(attachmentMeta ? { attachmentMeta } : {}),
            ...(model ? { model } : {}),
            ...(reasoningEffort ? { reasoningEffort } : {}),
          },
        });
      }
    } catch (error) {
      console.error('Error with workspace:', error);
      toast({
        variant: 'destructive',
        title: 'Error',
        description: 'Failed to access workspace. Please try again.',
      });
    } finally {
      setIsLoading(false);
    }
  };

  return {
    mode,
    setMode,
    isLoading,
    handleSend,
    workspaces,
    selectedWorkspaceId,
    setSelectedWorkspaceId,
  };
}
