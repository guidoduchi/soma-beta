import {createRoot} from 'react-dom/client';
import {AppearanceSettings, type AppearanceWriter} from '../components/AppearanceSettings';
import '../styles/soma.css';
const writer: AppearanceWriter = async request => {
  // Fixture-only owner seam deliberately rejects. It creates no operational state.
  if (request.base_revision !== null || !request.command_id) throw new Error('Invalid fixture command');
  await new Promise(resolve => setTimeout(resolve, 50));
  throw new Error('Synthetic owner write rejection');
};
createRoot(document.getElementById('root')!).render(<main><h1>Synthetic appearance settings</h1><AppearanceSettings writeSetting={writer}/></main>);
