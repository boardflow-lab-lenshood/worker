using System;
using System.Data.Common;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Text.Json;
using Npgsql;
using StackExchange.Redis;

namespace Worker
{
    public class Program
    {
        public static int Main(string[] args)
        {
            if (args.Length == 1 && args[0] == "--version")
            {
                Console.WriteLine(JsonSerializer.Serialize(new
                {
                    service = "worker",
                    version = "arena-seven-20261103"
                }));
                return 0;
            }

            try
            {
                var pgsql = OpenDbConnection(Environment.GetEnvironmentVariable("DATABASE_CONNECTION_STRING")
                    ?? throw new InvalidOperationException("DATABASE_CONNECTION_STRING is required"));
                var redisConn = OpenRedisConnection("redis");
                var redis = redisConn.GetDatabase();

                // Keep alive is not implemented in Npgsql yet. This workaround was recommended:
                // https://github.com/npgsql/npgsql/issues/1214#issuecomment-235828359
                var keepAliveCommand = pgsql.CreateCommand();
                keepAliveCommand.CommandText = "SELECT 1";

                while (true)
                {
                    // Slow down to prevent CPU spike, only query each 100ms
                    Thread.Sleep(100);

                    // Reconnect redis if down
                    if (redisConn == null || !redisConn.IsConnected) {
                        Console.WriteLine("Reconnecting Redis");
                        redisConn = OpenRedisConnection("redis");
                        redis = redisConn.GetDatabase();
                    }
                    string json = redis.ListLeftPopAsync("votes").Result;
                    if (json != null)
                    {
                        if (!TryReadVote(json, out var voterId, out var vote))
                        {
                            continue;
                        }
                        // Reconnect DB if down
                        if (!pgsql.State.Equals(System.Data.ConnectionState.Open))
                        {
                            Console.WriteLine("Reconnecting DB");
                            pgsql = OpenDbConnection(Environment.GetEnvironmentVariable("DATABASE_CONNECTION_STRING")
                                ?? throw new InvalidOperationException("DATABASE_CONNECTION_STRING is required"));
                        }
                        else
                        { // Normal +1 vote requested
                            UpdateVote(pgsql, voterId, vote);
                        }
                    }
                    else
                    {
                        keepAliveCommand.ExecuteNonQuery();
                    }
                }
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine(ex.ToString());
                return 1;
            }
        }

        private enum RejectionReason
        {
            InvalidJson,
            NonObject,
            MissingVoterId,
            MissingVote,
            InvalidVoterIdType,
            InvalidVoteType,
            InvalidVoterId,
            InvalidVote
        }

        private static bool RejectVote(RejectionReason reason)
        {
            Console.Error.WriteLine(JsonSerializer.Serialize(new
            {
                @event = "vote_rejected",
                reason = reason.ToString()
            }));
            return false;
        }

        private static bool TryReadVote(string json, out string voterId, out string vote)
        {
            voterId = null;
            vote = null;
            JsonDocument message;
            try
            {
                message = JsonDocument.Parse(json);
            }
            catch (JsonException)
            {
                return RejectVote(RejectionReason.InvalidJson);
            }

            using (message)
            {
                var root = message.RootElement;
                if (root.ValueKind != JsonValueKind.Object)
                    return RejectVote(RejectionReason.NonObject);
                try
                {
                    if (!root.TryGetProperty("voter_id", out var idField))
                        return RejectVote(RejectionReason.MissingVoterId);
                    if (!root.TryGetProperty("vote", out var voteField))
                        return RejectVote(RejectionReason.MissingVote);
                    if (idField.ValueKind != JsonValueKind.String)
                        return RejectVote(RejectionReason.InvalidVoterIdType);
                    if (voteField.ValueKind != JsonValueKind.String)
                        return RejectVote(RejectionReason.InvalidVoteType);

                    voterId = idField.GetString();
                    vote = voteField.GetString();
                }
                catch (InvalidOperationException)
                {
                    // Invalid escaped UTF-16 can fail decoding in property lookup or GetString.
                    return RejectVote(RejectionReason.InvalidJson);
                }
                if (string.IsNullOrWhiteSpace(voterId) || voterId.Contains('\0') ||
                    voterId.EnumerateRunes().Take(256).Count() > 255)
                    return RejectVote(RejectionReason.InvalidVoterId);
                if (vote != "a" && vote != "b")
                    return RejectVote(RejectionReason.InvalidVote);
                return true;
            }
        }

        private static NpgsqlConnection OpenDbConnection(string connectionString)
        {
            NpgsqlConnection connection;

            while (true)
            {
                try
                {
                    connection = new NpgsqlConnection(connectionString);
                    connection.Open();
                    break;
                }
                catch (SocketException)
                {
                    Console.Error.WriteLine("Waiting for db");
                    Thread.Sleep(1000);
                }
                catch (DbException)
                {
                    Console.Error.WriteLine("Waiting for db");
                    Thread.Sleep(1000);
                }
            }

            Console.Error.WriteLine("Connected to db");

            var command = connection.CreateCommand();
            command.CommandText = @"CREATE TABLE IF NOT EXISTS votes (
                                        id VARCHAR(255) NOT NULL UNIQUE,
                                        vote VARCHAR(255) NOT NULL
                                    )";
            command.ExecuteNonQuery();

            return connection;
        }

        private static ConnectionMultiplexer OpenRedisConnection(string hostname)
        {
            // Use IP address to workaround https://github.com/StackExchange/StackExchange.Redis/issues/410
            var ipAddress = GetIp(hostname);
            Console.WriteLine($"Found redis at {ipAddress}");

            while (true)
            {
                try
                {
                    Console.Error.WriteLine("Connecting to redis");
                    return ConnectionMultiplexer.Connect(ipAddress);
                }
                catch (RedisConnectionException)
                {
                    Console.Error.WriteLine("Waiting for redis");
                    Thread.Sleep(1000);
                }
            }
        }

        private static string GetIp(string hostname)
            => Dns.GetHostEntryAsync(hostname)
                .Result
                .AddressList
                .First(a => a.AddressFamily == AddressFamily.InterNetwork)
                .ToString();

        private static void UpdateVote(NpgsqlConnection connection, string voterId, string vote)
        {
            var command = connection.CreateCommand();
            try
            {
                command.CommandText = "INSERT INTO votes (id, vote) VALUES (@id, @vote)";
                command.Parameters.AddWithValue("@id", voterId);
                command.Parameters.AddWithValue("@vote", vote);
                command.ExecuteNonQuery();
            }
            catch (PostgresException ex) when (ex.SqlState == PostgresErrorCodes.UniqueViolation)
            {
                command.CommandText = "UPDATE votes SET vote = @vote WHERE id = @id";
                command.ExecuteNonQuery();
            }
            finally
            {
                command.Dispose();
            }
        }
    }
}
