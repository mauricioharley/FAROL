import React from 'react';

// SVG desenhado a mao, sem biblioteca de grafico: o volume de dado aqui e'
// pequeno (no maximo um ponto por dia, ate 365 pontos) e o formato e' sempre
// o mesmo (barra por dia) - nao justifica puxar uma dependencia so' para
// isso. Se o painel gerencial crescer para mais tipos de grafico, vale
// reavaliar.
export default function GraficoTendencia({ dias }) {
  if (!dias || dias.length === 0) {
    return <p className="vazio">Sem dado suficiente no periodo para tracar tendencia.</p>;
  }

  const largura = 720;
  const altura = 180;
  const margemEsquerda = 30;
  const margemBaixo = 24;
  const areaLargura = largura - margemEsquerda - 10;
  const areaAltura = altura - margemBaixo - 10;

  const maximo = Math.max(1, ...dias.map((d) => d.total));
  const larguraBarra = areaLargura / dias.length;

  return (
    <>
      <svg className="chart-svg" viewBox={`0 0 ${largura} ${altura}`} width="100%" role="img"
           aria-label="Achados por dia nos ultimos dias">
        <line x1={margemEsquerda} y1={10} x2={margemEsquerda} y2={altura - margemBaixo}
              stroke="var(--border)" strokeWidth="1" />
        <line x1={margemEsquerda} y1={altura - margemBaixo} x2={largura} y2={altura - margemBaixo}
              stroke="var(--border)" strokeWidth="1" />
        {dias.map((d, i) => {
          const x = margemEsquerda + i * larguraBarra + larguraBarra * 0.15;
          const larguraReal = larguraBarra * 0.7;
          const alturaRisco = (d.achados_alto_risco / maximo) * areaAltura;
          const alturaTotal = (d.total / maximo) * areaAltura;
          const yBase = altura - margemBaixo;
          const mostrarRotulo = dias.length <= 15 || i % Math.ceil(dias.length / 15) === 0;
          return (
            <g key={d.dia}>
              <rect x={x} y={yBase - alturaTotal} width={larguraReal} height={alturaTotal}
                    fill="var(--surface-2)" />
              <rect x={x} y={yBase - alturaRisco} width={larguraReal} height={alturaRisco}
                    fill="var(--crit)" opacity="0.75" />
              {mostrarRotulo && (
                <text x={x + larguraReal / 2} y={altura - 6} textAnchor="middle">
                  {d.dia.slice(5)}
                </text>
              )}
            </g>
          );
        })}
        <text x={4} y={16}>{maximo}</text>
      </svg>
      <div className="chart-legenda">
        <span className="chart-legenda-item">
          <span className="chart-legenda-cor" style={{ background: 'var(--surface-2)' }} />
          Total de achados
        </span>
        <span className="chart-legenda-item">
          <span className="chart-legenda-cor" style={{ background: 'var(--crit)', opacity: 0.75 }} />
          Alto risco
        </span>
      </div>
    </>
  );
}
