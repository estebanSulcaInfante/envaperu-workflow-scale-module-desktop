import { useState } from 'react';
import { pesajesApi } from '../services/api';
import './GenerarRDP.css'; // Usamos los mismos estilos del modal

export default function ExportarExcel({ onClose }) {
  // Por defecto, último mes hasta hoy
  const hoy = new Date();
  const haceUnMes = new Date();
  haceUnMes.setMonth(haceUnMes.getMonth() - 1);
  
  const formatDate = (date) => date.toISOString().split('T')[0];
  
  const [fechaInicio, setFechaInicio] = useState(formatDate(haceUnMes));
  const [fechaFin, setFechaFin] = useState(formatDate(hoy));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleExportar = async () => {
    try {
      setLoading(true);
      setError('');
      
      const response = await pesajesApi.exportarExcel(fechaInicio, fechaFin);
      
      // Crear un blob link para descargar
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      
      // Extraer nombre del archivo si viene en los headers, o usar default
      let filename = 'pesajes.xlsx';
      const disposition = response.headers['content-disposition'];
      if (disposition && disposition.indexOf('attachment') !== -1) {
          const filenameRegex = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/;
          const matches = filenameRegex.exec(disposition);
          if (matches != null && matches[1]) { 
              filename = matches[1].replace(/['"]/g, '');
          }
      }
      
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.parentNode.removeChild(link);
      
      onClose();
    } catch (err) {
      console.error('Error exportando Excel:', err);
      // Extraer msj de error si viene en JSON a pesar de ser blob
      if (err.response && err.response.data && err.response.data.text) {
        try {
          const textData = await err.response.data.text();
          const jsonError = JSON.parse(textData);
          if (jsonError.error) {
             setError(jsonError.error);
             return;
          }
        } catch (e) {}
      }
      setError('Hubo un error al generar el Excel. Intente nuevamente.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content rdp-modal">
        <div className="modal-header">
          <h2>📊 Exportar a Excel</h2>
          <button className="btn-close" onClick={onClose}>&times;</button>
        </div>
        
        <div className="modal-body">
          <p>Seleccione el rango de fechas para exportar los pesajes.</p>
          
          {error && <div className="alert-error" style={{ color: 'red', marginBottom: '1rem' }}>{error}</div>}
          
          <div className="form-group" style={{ marginTop: '1rem' }}>
            <label>Fecha Inicio:</label>
            <input 
              type="date" 
              value={fechaInicio} 
              onChange={(e) => setFechaInicio(e.target.value)} 
              disabled={loading}
              max={fechaFin}
            />
          </div>
          
          <div className="form-group">
            <label>Fecha Fin:</label>
            <input 
              type="date" 
              value={fechaFin} 
              onChange={(e) => setFechaFin(e.target.value)} 
              disabled={loading}
              min={fechaInicio}
            />
          </div>
        </div>
        
        <div className="modal-footer">
          <button 
            className="btn btn-secondary" 
            onClick={onClose}
            disabled={loading}
          >
            Cancelar
          </button>
          <button 
            className="btn btn-primary" 
            onClick={handleExportar}
            disabled={loading}
          >
            {loading ? '⏳ Generando Excel...' : '📥 Descargar Excel'}
          </button>
        </div>
      </div>
    </div>
  );
}
