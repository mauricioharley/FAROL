import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import GraficoTendencia from './GraficoTendencia.jsx';

describe('GraficoTendencia', () => {
  it('mostra mensagem de dado insuficiente quando dias esta vazio', () => {
    render(<GraficoTendencia dias={[]} />);

    expect(screen.getByText('Sem dado suficiente no periodo para tracar tendencia.')).toBeInTheDocument();
    expect(document.querySelector('svg')).not.toBeInTheDocument();
  });

  it('mostra mensagem de dado insuficiente quando dias e null', () => {
    render(<GraficoTendencia dias={null} />);

    expect(screen.getByText(/Sem dado suficiente/)).toBeInTheDocument();
    expect(document.querySelector('svg')).not.toBeInTheDocument();
  });

  it('desenha o svg quando ha dados', () => {
    render(<GraficoTendencia dias={[{ dia: '2026-08-01', total: 5, achados_alto_risco: 1 }]} />);

    expect(document.querySelector('svg')).toBeInTheDocument();
    expect(screen.queryByText(/Sem dado suficiente/)).not.toBeInTheDocument();
  });
});
