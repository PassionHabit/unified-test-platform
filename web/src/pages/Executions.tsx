import { useEffect, useState } from "react";
import { Table, Tag, Select, Space, Button, Typography } from "antd";
import { Link } from "react-router-dom";
import { api, STATUS_COLOR, OUTCOME_COLOR } from "../api";

const STATUSES = [
  "QUEUED", "PREPARING", "STARTING", "RUNNING", "RECONCILING",
  "CANCELLING", "FINALIZING", "COMPLETED", "FAILED", "CANCELLED",
];

export default function Executions() {
  const [rows, setRows] = useState<any[]>([]);
  const [status, setStatus] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    const q = new URLSearchParams();
    if (status) q.set("status", status);
    api(`/api/v1/executions?${q}`)
      .then(setRows)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [status]);

  return (
    <Cardless
      title={
        <Space>
          <Typography.Title level={5} style={{ margin: 0 }}>执行列表</Typography.Title>
          <Select
            allowClear
            placeholder="按状态过滤"
            style={{ width: 160 }}
            value={status}
            onChange={setStatus}
            options={STATUSES.map((s) => ({ value: s, label: s }))}
          />
        </Space>
      }
    >
      <Table
        rowKey="id"
        size="middle"
        loading={loading}
        dataSource={rows}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: "ID", dataIndex: "id", width: 70 },
          { title: "项目", dataIndex: "project_id", width: 110 },
          { title: "Profile", dataIndex: "profile_name", width: 110 },
          {
            title: "状态", dataIndex: "status", width: 120,
            render: (s) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
          },
          {
            title: "结论", dataIndex: "outcome", width: 110,
            render: (o) => <Tag color={OUTCOME_COLOR[o]}>{o}</Tag>,
          },
          { title: "失败原因", dataIndex: "failure_reason", width: 170 },
          { title: "创建时间", dataIndex: "created_at", width: 190, render: (t) => t?.replace("T", " ").slice(0, 19) },
          {
            title: "", width: 90,
            render: (_: any, r: any) => (
              <Link to={`/executions/${r.id}`}>
                <Button size="small">详情</Button>
              </Link>
            ),
          },
        ]}
      />
    </Cardless>
  );
}

function Cardless({ title, children }: any) {
  return (
    <div className="ant-card ant-card-bordered" style={{ background: "#fff", padding: 16 }}>
      <div style={{ marginBottom: 12 }}>{title}</div>
      {children}
    </div>
  );
}
