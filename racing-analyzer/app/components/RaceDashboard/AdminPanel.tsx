// The admin UI now lives in the shared <AdminManager>. This re-export keeps the
// dashboard's existing `import AdminPanel from './AdminPanel'` working.
export { default } from '../AdminManager';
