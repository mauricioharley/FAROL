import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from './App.jsx';

const RESUMO = {
  score_conformidade: 82,
  cobertura: 91,
  recursos_auditados: 120,
  pendentes_revisao: 3,
  confirmados: 1,
};
const ORGAOS = {
  orgaos: [
    { org: 'SME', recursos_auditados: 40, achados_alto_risco: 2, pendentes_revisao: 1, nao_analisados: 0 },
  ],
};
const TENDENCIA = {
  dias: [{ dia: '2026-08-01', total: 5, achados_alto_risco: 1 }],
};

function respostaJson(corpo, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(corpo),
  });
}

function mockFetchPadrao() {
  return vi.fn((caminho) => {
    if (caminho.includes('/api/gerencial/resumo')) return respostaJson(RESUMO);
    if (caminho.includes('/api/gerencial/por-orgao')) return respostaJson(ORGAOS);
    if (caminho.includes('/api/gerencial/tendencia')) return respostaJson(TENDENCIA);
    throw new Error(`rota nao mockada: ${caminho}`);
  });
}

describe('App', () => {
  const localizacaoOriginal = window.location;

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Object.defineProperty(window, 'location', { writable: true, value: localizacaoOriginal });
  });

  it('nao mostra as secoes antes das chamadas resolverem, e mostra depois', async () => {
    let resolverResumo;
    const resumoPendente = new Promise((resolve) => {
      resolverResumo = resolve;
    });
    global.fetch = vi.fn((caminho) => {
      if (caminho.includes('/api/gerencial/resumo')) return resumoPendente;
      if (caminho.includes('/api/gerencial/por-orgao')) return respostaJson(ORGAOS);
      if (caminho.includes('/api/gerencial/tendencia')) return respostaJson(TENDENCIA);
      throw new Error(`rota nao mockada: ${caminho}`);
    });

    render(<App />);

    expect(screen.queryByText('Visao geral')).not.toBeInTheDocument();
    expect(screen.queryByText(/Achados por dia/)).not.toBeInTheDocument();
    expect(screen.queryByText('Ranking por orgao')).not.toBeInTheDocument();
    expect(screen.getByText(/Carregando dados/)).toBeInTheDocument();

    resolverResumo(respostaJson(RESUMO));

    await waitFor(() => expect(screen.getByText('Visao geral')).toBeInTheDocument());
    expect(screen.getByText(/Achados por dia/)).toBeInTheDocument();
    expect(screen.getByText('Ranking por orgao')).toBeInTheDocument();
    expect(screen.queryByText(/Carregando dados/)).not.toBeInTheDocument();
  });

  it('mostra os cards de Visao geral com os valores mockados no caminho feliz', async () => {
    global.fetch = mockFetchPadrao();

    render(<App />);

    await waitFor(() => expect(screen.getByText('Visao geral')).toBeInTheDocument());
    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getByText('91%')).toBeInTheDocument();
    expect(screen.getByText('120')).toBeInTheDocument();
    expect(screen.getByText('SME')).toBeInTheDocument();
  });

  it('redireciona para login-gerencial quando uma chamada volta 401', async () => {
    Object.defineProperty(window, 'location', { writable: true, value: { href: '' } });

    global.fetch = vi.fn((caminho) => {
      if (caminho.includes('/api/gerencial/resumo')) return respostaJson({}, 401);
      if (caminho.includes('/api/gerencial/por-orgao')) return respostaJson(ORGAOS);
      if (caminho.includes('/api/gerencial/tendencia')) return respostaJson(TENDENCIA);
      throw new Error(`rota nao mockada: ${caminho}`);
    });

    render(<App />);

    await waitFor(() => expect(screen.getByText(/Sessao expirada/)).toBeInTheDocument());
    expect(window.location.href).toBe('');

    await waitFor(
      () => expect(window.location.href).toBe('/login-gerencial?proximo=/gerencial&motivo=sessao-expirada'),
      { timeout: 2000 },
    );
  });
});
