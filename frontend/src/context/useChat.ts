import { useContext } from 'react';
import { ChatContext } from './chatContextDef';
import type { ChatContextType } from './chatContextDef';

export const useChat = (): ChatContextType => {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return context;
};

export default useChat;
